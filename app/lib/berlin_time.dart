/// Berlin time without shipping a time zone database: the EU rule since 1996 puts Berlin on UTC+2 from 01:00 UTC on
/// the last Sunday of March to 01:00 UTC on the last Sunday of October, and on UTC+1 otherwise.
const int _summerTimeStartMonth = DateTime.march;
const int _summerTimeEndMonth = DateTime.october;
const _clockChangeHourUtc = 1;
const _winterOffset = Duration(hours: 1);
const _summerOffset = Duration(hours: 2);

DateTime _lastSundayOfMonthAtChange(int year, int month) {
  final lastDay = DateTime.utc(year, month + 1, 0);
  final lastSunday = lastDay.subtract(Duration(days: lastDay.weekday % DateTime.daysPerWeek));
  return DateTime.utc(lastSunday.year, lastSunday.month, lastSunday.day, _clockChangeHourUtc);
}

Duration berlinOffset(DateTime instant) {
  final utc = instant.toUtc();
  final summerStarts = _lastSundayOfMonthAtChange(utc.year, _summerTimeStartMonth);
  final summerEnds = _lastSundayOfMonthAtChange(utc.year, _summerTimeEndMonth);
  return !utc.isBefore(summerStarts) && utc.isBefore(summerEnds) ? _summerOffset : _winterOffset;
}

/// A UTC-flagged value whose fields read as the Berlin wall clock; only for display and for picking the day.
DateTime berlinWallClock(DateTime instant) => instant.toUtc().add(berlinOffset(instant));

/// The Berlin calendar day of an instant, as `YYYY-MM-DD`.
String berlinDay(DateTime instant) => berlinWallClock(instant).toIso8601String().substring(0, 10);

/// `18:00` for an hour starting at 18:00 Berlin time.
String berlinHourLabel(DateTime instant) {
  final wallClock = berlinWallClock(instant);
  return '${wallClock.hour.toString().padLeft(2, '0')}:00';
}
