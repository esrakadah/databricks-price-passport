import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:price_passport_api/price_passport_api.dart';
import 'package:test/test.dart';

final Uri _host = Uri.parse('https://workspace.example');

void main() {
  late DateTime now;
  DateTime clock() => now;
  setUp(() => now = DateTime.utc(2026, 10, 29, 12));

  ServicePrincipal principal() => ServicePrincipal(host: _host, clientId: 'reader', clientSecret: 'secret');

  http.Response tokenResponse(String token) =>
      http.Response(jsonEncode({'access_token': token, 'expires_in': 3600}), 200);

  group('OAuthTokenSource', () {
    test('reuses a token until shortly before it expires', () async {
      var issued = 0;
      final client = MockClient((request) async {
        expect(request.url.path, '/oidc/v1/token');
        expect(request.bodyFields['grant_type'], 'client_credentials');
        issued++;
        return tokenResponse('token-$issued');
      });
      final tokens = OAuthTokenSource(principal(), client: client, clock: clock);

      expect(await tokens.token(), 'token-1');
      now = now.add(const Duration(minutes: 54));
      expect(await tokens.token(), 'token-1');
      now = now.add(const Duration(minutes: 2));
      expect(await tokens.token(), 'token-2');
    });

    test('fails clearly when the token request is refused', () async {
      final tokens = OAuthTokenSource(
        principal(),
        client: MockClient((_) async => http.Response('nope', 401)),
        clock: clock,
      );

      expect(tokens.token, throwsA(isA<DatabricksException>()));
    });
  });

  group('SqlStatementClient', () {
    Map<String, Object?> statement(String state, {List<List<String?>>? rows, String? error}) => {
      'statement_id': 'statement-1',
      'status': {
        'state': state,
        if (error != null) 'error': {'message': error},
      },
      if (rows != null) ...{
        'manifest': {
          'schema': {
            'columns': [
              {'name': 'hour_start'},
              {'name': 'price_eur_mwh'},
            ],
          },
        },
        'result': {'data_array': rows},
      },
    };

    SqlStatementClient sqlClient(List<Map<String, Object?>> answers, {List<http.Request>? seen}) {
      final queue = [...answers];
      final client = MockClient((request) async {
        if (request.url.path == '/oidc/v1/token') return tokenResponse('token');
        seen?.add(request);
        return http.Response(jsonEncode(queue.removeAt(0)), 200);
      });
      return SqlStatementClient(
        host: _host,
        warehouseId: 'warehouse-1',
        tokens: OAuthTokenSource(principal(), client: client, clock: clock),
        client: client,
        clock: clock,
        delay: (duration) async => now = now.add(duration),
      );
    }

    test('waits for a cold warehouse and returns the rows by column name', () async {
      final seen = <http.Request>[];
      final sql = sqlClient([
        statement('PENDING'),
        statement('RUNNING'),
        statement(
          'SUCCEEDED',
          rows: [
            ['2026-10-27T23:00:00.000Z', '120.5'],
          ],
        ),
      ], seen: seen);

      final result = await sql.execute('SELECT 1', parameters: {'day': '2026-10-28'});

      expect(result.records.single, {'hour_start': '2026-10-27T23:00:00.000Z', 'price_eur_mwh': '120.5'});
      expect(seen.first.method, 'POST');
      final sent = jsonDecode(seen.first.body) as Map<String, dynamic>;
      expect(sent['parameters'], [
        {'name': 'day', 'value': '2026-10-28'},
      ]);
      expect(seen.skip(1).every((request) => request.url.path.endsWith('/statement-1')), isTrue);
    });

    test('gives up after the deadline instead of hanging', () async {
      final sql = sqlClient(List.generate(100, (_) => statement('PENDING')));

      expect(() => sql.execute('SELECT 1'), throwsA(isA<DatabricksException>()));
    });

    test('reports a failed statement with its message', () async {
      final sql = sqlClient([statement('FAILED', error: 'TABLE_OR_VIEW_NOT_FOUND')]);

      expect(
        () => sql.execute('SELECT 1'),
        throwsA(isA<DatabricksException>().having((error) => error.message, 'message', contains('TABLE_OR_VIEW'))),
      );
    });
  });
}
