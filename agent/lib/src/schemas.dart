import 'package:schemantic/schemantic.dart';

part 'schemas.g.dart';

@Schema()
abstract class $DayLookup {
  @StringField(description: 'The delivery day in Berlin time, as YYYY-MM-DD, for example 2026-10-30')
  String get day;
}

@Schema()
abstract class $PriceQuestion {
  @StringField(
    description: 'A question about a price, in plain language, for example "Why is 18:00 tomorrow so expensive?"',
  )
  String get question;
}

@Schema()
abstract class $PriceAnswer {
  String get answer;

  /// The delivery days the agent looked up to answer, so the app can link them.
  List<String> get days;
}
