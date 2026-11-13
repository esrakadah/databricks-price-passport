import 'package:flutter_test/flutter_test.dart';
import 'package:price_passport_app/berlin_time.dart';

void main() {
  test('summer time starts at 01:00 UTC on the last Sunday of March', () {
    expect(berlinOffset(DateTime.utc(2026, 3, 29, 0, 59)), const Duration(hours: 1));
    expect(berlinOffset(DateTime.utc(2026, 3, 29, 1)), const Duration(hours: 2));
  });

  test('summer time ends at 01:00 UTC on the last Sunday of October', () {
    expect(berlinOffset(DateTime.utc(2026, 10, 25, 0, 59)), const Duration(hours: 2));
    expect(berlinOffset(DateTime.utc(2026, 10, 25, 1)), const Duration(hours: 1));
  });

  test('the Berlin day starts an hour or two before the UTC day', () {
    expect(berlinDay(DateTime.utc(2026, 10, 27, 23)), '2026-10-28');
    expect(berlinDay(DateTime.utc(2026, 7, 1, 22)), '2026-07-02');
    expect(berlinDay(DateTime.utc(2026, 7, 1, 21, 59)), '2026-07-01');
  });

  test('hour labels read as the Berlin wall clock', () {
    expect(berlinHourLabel(DateTime.utc(2026, 10, 27, 23)), '00:00');
    expect(berlinHourLabel(DateTime.utc(2026, 6, 1, 16)), '18:00');
  });
}
