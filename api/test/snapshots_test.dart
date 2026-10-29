import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:price_passport_api/price_passport_api.dart';
import 'package:test/test.dart';

DeliveryDayPrices _day(String source, DateTime fetchedAt) => DeliveryDayPrices(
  deliveryDay: '2026-10-28',
  hours: [
    HourlyPrice(
      hourStart: DateTime.utc(2026, 10, 27, 23),
      priceEurMwh: 99.5,
      isComplete: true,
    ),
  ],
  fetchedAt: fetchedAt,
  source: source,
);

class _FakeBucket {
  final objects = <String, String>{};
  int uploads = 0;
  bool failUploads = false;

  MockClient get client => MockClient((request) async {
    expect(request.headers['Authorization'], 'Bearer service-account-token');
    if (request.method == 'POST') {
      uploads++;
      if (failUploads) return http.Response('quota', 429);
      objects[request.url.queryParameters['name']!] = request.body;
      return http.Response('{}', 200);
    }
    final name = Uri.decodeComponent(request.url.pathSegments.last);
    final stored = objects[name];
    return stored == null ? http.Response('', 404) : http.Response(stored, 200);
  });
}

void main() {
  final fetchedYesterday = DateTime.utc(2026, 10, 28, 9);
  late _FakeBucket bucket;
  late CloudStorageSnapshots snapshots;

  setUp(() {
    bucket = _FakeBucket();
    snapshots = CloudStorageSnapshots(
      bucket: 'snapshots',
      client: bucket.client,
      token: () async => 'service-account-token',
    );
  });

  test('a live answer is stored and returned unchanged', () async {
    final lookup = withSnapshotFallback(
      (day) async => _day('live', fetchedYesterday),
      snapshots,
    );

    final answer = await lookup('2026-10-28');

    expect(answer.source, 'live');
    expect(bucket.objects.keys, ['prices/2026-10-28.json']);
  });

  test(
    'a failed live read is answered from the snapshot with its original fetch time',
    () async {
      await snapshots.save(_day('live', fetchedYesterday));
      final lookup = withSnapshotFallback(
        (day) async => throw Exception('quota exceeded'),
        snapshots,
      );

      final answer = await lookup('2026-10-28');

      expect(answer.source, 'snapshot');
      expect(answer.fetchedAt, fetchedYesterday);
      expect(answer.hours.single.priceEurMwh, 99.5);
    },
  );

  test('without a snapshot the live error reaches the caller', () async {
    final lookup = withSnapshotFallback(
      (day) async => throw Exception('quota exceeded'),
      snapshots,
    );

    expect(() => lookup('2026-10-28'), throwsException);
  });

  test('a failed upload never fails a good live answer', () async {
    bucket.failUploads = true;
    final lookup = withSnapshotFallback(
      (day) async => _day('live', fetchedYesterday),
      snapshots,
    );

    final answer = await lookup('2026-10-28');

    expect(answer.source, 'live');
    expect(bucket.uploads, 1);
  });

  test(
    'the metadata token is cached until shortly before it expires',
    () async {
      var now = DateTime.utc(2026, 10, 29, 12);
      var issued = 0;
      final tokens = MetadataTokenSource(
        client: MockClient((request) async {
          expect(request.headers['Metadata-Flavor'], 'Google');
          issued++;
          return http.Response(
            jsonEncode({'access_token': 'token-$issued', 'expires_in': 3600}),
            200,
          );
        }),
        clock: () => now,
      );

      expect(await tokens.token(), 'token-1');
      now = now.add(const Duration(minutes: 50));
      expect(await tokens.token(), 'token-1');
      now = now.add(const Duration(minutes: 6));
      expect(await tokens.token(), 'token-2');
    },
  );
}
