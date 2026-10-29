import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

/// Returns the current time; injected so token expiry and cache ages are testable.
typedef Clock = DateTime Function();

/// Waits between polls of a running statement; injected so tests do not sleep.
typedef Delay = Future<void> Function(Duration duration);

/// A Databricks call that failed or returned something this service cannot use.
class DatabricksException implements Exception {
  DatabricksException(this.message);

  final String message;

  @override
  String toString() => 'DatabricksException: $message';
}

/// OAuth machine-to-machine credentials of the read-only service principal `price-passport-reader`
/// (decisions section 5).
class ServicePrincipal {
  const ServicePrincipal({required this.host, required this.clientId, required this.clientSecret});

  final Uri host;
  final String clientId;
  final String clientSecret;
}

/// Fetches and caches workspace OAuth tokens with the client-credentials grant.
class OAuthTokenSource {
  OAuthTokenSource(this._principal, {required this._client, required this._clock});

  /// Tokens are refreshed this long before they expire, so a request never starts with a token about to lapse.
  static const refreshMargin = Duration(minutes: 5);

  final ServicePrincipal _principal;
  final http.Client _client;
  final Clock _clock;
  String? _token;
  DateTime? _expiresAt;

  Future<String> token() async {
    final cached = _token;
    final expiresAt = _expiresAt;
    if (cached != null && expiresAt != null && _clock().isBefore(expiresAt.subtract(refreshMargin))) {
      return cached;
    }
    final credentials = base64Encode(utf8.encode('${_principal.clientId}:${_principal.clientSecret}'));
    final response = await _client.post(
      _principal.host.resolve('/oidc/v1/token'),
      headers: {'Authorization': 'Basic $credentials', 'Content-Type': 'application/x-www-form-urlencoded'},
      body: {'grant_type': 'client_credentials', 'scope': 'all-apis'},
    );
    if (response.statusCode != 200) {
      throw DatabricksException('token request failed with HTTP ${response.statusCode}');
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    final token = body['access_token'] as String;
    _token = token;
    _expiresAt = _clock().add(Duration(seconds: (body['expires_in'] as num).toInt()));
    return token;
  }
}

/// The rows of a finished statement, by column name.
class StatementResult {
  const StatementResult(this.columns, this.rows);

  final List<String> columns;
  final List<List<String?>> rows;

  List<Map<String, String?>> get records => [
    for (final row in rows) {for (var index = 0; index < columns.length; index++) columns[index]: row[index]},
  ];
}

/// Runs SQL on a warehouse through the Statement Execution API, waiting for a cold warehouse up to a deadline.
class SqlStatementClient {
  SqlStatementClient({
    required this._host,
    required this._warehouseId,
    required this._tokens,
    required this._client,
    required this._clock,
    this._delay = Future<void>.delayed,
  });

  /// The single 2X-Small Free Edition warehouse can take well over a minute to start.
  static const deadline = Duration(seconds: 90);
  static const pollInterval = Duration(seconds: 3);
  static const _serverWait = '30s';

  final Uri _host;
  final String _warehouseId;
  final OAuthTokenSource _tokens;
  final http.Client _client;
  final Clock _clock;
  final Delay _delay;

  Future<StatementResult> execute(String statement, {Map<String, String> parameters = const {}}) async {
    final giveUpAt = _clock().add(deadline);
    var body = await _send(
      'POST',
      '/api/2.0/sql/statements',
      jsonEncode({
        'warehouse_id': _warehouseId,
        'statement': statement,
        'wait_timeout': _serverWait,
        'on_wait_timeout': 'CONTINUE',
        'format': 'JSON_ARRAY',
        'disposition': 'INLINE',
        'parameters': [
          for (final entry in parameters.entries) {'name': entry.key, 'value': entry.value},
        ],
      }),
    );
    while (_state(body) == 'PENDING' || _state(body) == 'RUNNING') {
      if (!_clock().isBefore(giveUpAt)) {
        throw DatabricksException('statement still ${_state(body)} after ${deadline.inSeconds} s');
      }
      await _delay(pollInterval);
      body = await _send('GET', '/api/2.0/sql/statements/${body['statement_id']}', null);
    }
    if (_state(body) != 'SUCCEEDED') {
      final error = (body['status'] as Map<String, dynamic>)['error'] as Map<String, dynamic>?;
      throw DatabricksException('statement ${_state(body)}: ${error?['message'] ?? 'no message'}');
    }
    final manifest = body['manifest'] as Map<String, dynamic>;
    final columns = [
      for (final column in (manifest['schema'] as Map<String, dynamic>)['columns'] as List<dynamic>)
        (column as Map<String, dynamic>)['name'] as String,
    ];
    final data = (body['result'] as Map<String, dynamic>?)?['data_array'] as List<dynamic>? ?? const [];
    return StatementResult(columns, [
      for (final row in data) [for (final value in row as List<dynamic>) value as String?],
    ]);
  }

  String _state(Map<String, dynamic> body) => (body['status'] as Map<String, dynamic>)['state'] as String;

  Future<Map<String, dynamic>> _send(String method, String path, String? body) async {
    final request = http.Request(method, _host.resolve(path))
      ..headers['Authorization'] = 'Bearer ${await _tokens.token()}'
      ..headers['Content-Type'] = 'application/json';
    if (body != null) request.body = body;
    final response = await http.Response.fromStream(await _client.send(request));
    if (response.statusCode != 200) {
      throw DatabricksException('$method $path failed with HTTP ${response.statusCode}: ${_errorMessage(response)}');
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  /// Databricks explains a refusal in `message`; it names privileges and objects, never credentials.
  String _errorMessage(http.Response response) {
    try {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return '${body['error_code'] ?? ''} ${body['message'] ?? ''}'.trim();
    } on FormatException {
      return 'no error body';
    }
  }
}
