/// Berlin time by the EU rule since 1996: UTC+2 from 01:00 UTC on the last Sunday of March to 01:00 UTC on the last
/// Sunday of October, UTC+1 otherwise. The same rule as `app/lib/berlin_time.dart`; the agent is a separate package.
const int _summerTimeStartMonth = DateTime.march;
const int _summerTimeEndMonth = DateTime.october;
const _clockChangeHourUtc = 1;

DateTime _lastSundayAtChange(int year, int month) {
  final lastDay = DateTime.utc(year, month + 1, 0);
  final lastSunday = lastDay.subtract(Duration(days: lastDay.weekday % DateTime.daysPerWeek));
  return DateTime.utc(lastSunday.year, lastSunday.month, lastSunday.day, _clockChangeHourUtc);
}

/// `18:00` for an hour that starts at 18:00 Berlin time.
String berlinHourLabel(DateTime instant) {
  final utc = instant.toUtc();
  final summer =
      !utc.isBefore(_lastSundayAtChange(utc.year, _summerTimeStartMonth)) &&
      utc.isBefore(_lastSundayAtChange(utc.year, _summerTimeEndMonth));
  final wallClock = utc.add(Duration(hours: summer ? 2 : 1));
  return '${wallClock.hour.toString().padLeft(2, '0')}:00';
}
