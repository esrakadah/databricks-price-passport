// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'schemas.dart';

// **************************************************************************
// SchemaGenerator
// **************************************************************************

base class DayLookup {
  /// Creates a [DayLookup] from a JSON map.
  factory DayLookup.fromJson(Map<String, dynamic> json) => $schema.parse(json);

  DayLookup._(this._json);

  DayLookup({required String day}) {
    _json = {'day': day};
  }

  late final Map<String, dynamic> _json;

  /// The JSON schema and type descriptor for [DayLookup].
  static const SchemanticType<DayLookup> $schema = _DayLookupTypeFactory();

  String get day {
    return _json['day'] as String;
  }

  set day(String value) {
    _json['day'] = value;
  }

  @override
  String toString() {
    return _json.toString();
  }

  /// Serializes this [DayLookup] to a JSON map.
  Map<String, dynamic> toJson() {
    return _json;
  }
}

base class _DayLookupTypeFactory extends SchemanticType<DayLookup> {
  const _DayLookupTypeFactory();

  @override
  DayLookup parse(Object? json) {
    return DayLookup._(json as Map<String, dynamic>);
  }

  @override
  JsonSchemaMetadata get schemaMetadata => JsonSchemaMetadata(
    name: 'DayLookup',
    definition: <String, Object?>{
      'type': 'object',
      'properties': <String, Object?>{
        'day': <String, Object?>{
          'type': 'string',
          'description': 'The delivery day in Berlin time, as YYYY-MM-DD, for example 2026-10-30',
        },
      },
      'required': ['day'],
    },
    dependencies: [],
  );
}

base class PriceQuestion {
  /// Creates a [PriceQuestion] from a JSON map.
  factory PriceQuestion.fromJson(Map<String, dynamic> json) => $schema.parse(json);

  PriceQuestion._(this._json);

  PriceQuestion({required String question}) {
    _json = {'question': question};
  }

  late final Map<String, dynamic> _json;

  /// The JSON schema and type descriptor for [PriceQuestion].
  static const SchemanticType<PriceQuestion> $schema = _PriceQuestionTypeFactory();

  String get question {
    return _json['question'] as String;
  }

  set question(String value) {
    _json['question'] = value;
  }

  @override
  String toString() {
    return _json.toString();
  }

  /// Serializes this [PriceQuestion] to a JSON map.
  Map<String, dynamic> toJson() {
    return _json;
  }
}

base class _PriceQuestionTypeFactory extends SchemanticType<PriceQuestion> {
  const _PriceQuestionTypeFactory();

  @override
  PriceQuestion parse(Object? json) {
    return PriceQuestion._(json as Map<String, dynamic>);
  }

  @override
  JsonSchemaMetadata get schemaMetadata => JsonSchemaMetadata(
    name: 'PriceQuestion',
    definition: <String, Object?>{
      'type': 'object',
      'properties': <String, Object?>{
        'question': <String, Object?>{
          'type': 'string',
          'description':
              'A question about a price, in plain language, for example "Why is 18:00 tomorrow so expensive?"',
        },
      },
      'required': ['question'],
    },
    dependencies: [],
  );
}

base class PriceAnswer {
  /// Creates a [PriceAnswer] from a JSON map.
  factory PriceAnswer.fromJson(Map<String, dynamic> json) => $schema.parse(json);

  PriceAnswer._(this._json);

  PriceAnswer({required String answer, required List<String> days}) {
    _json = {'answer': answer, 'days': days};
  }

  late final Map<String, dynamic> _json;

  /// The JSON schema and type descriptor for [PriceAnswer].
  static const SchemanticType<PriceAnswer> $schema = _PriceAnswerTypeFactory();

  String get answer {
    return _json['answer'] as String;
  }

  set answer(String value) {
    _json['answer'] = value;
  }

  /// The delivery days the agent looked up to answer, so the app can link them.
  List<String> get days {
    return (_json['days'] as List).cast<String>();
  }

  /// The delivery days the agent looked up to answer, so the app can link them.
  set days(List<String> value) {
    _json['days'] = value;
  }

  @override
  String toString() {
    return _json.toString();
  }

  /// Serializes this [PriceAnswer] to a JSON map.
  Map<String, dynamic> toJson() {
    return _json;
  }
}

base class _PriceAnswerTypeFactory extends SchemanticType<PriceAnswer> {
  const _PriceAnswerTypeFactory();

  @override
  PriceAnswer parse(Object? json) {
    return PriceAnswer._(json as Map<String, dynamic>);
  }

  @override
  JsonSchemaMetadata get schemaMetadata => JsonSchemaMetadata(
    name: 'PriceAnswer',
    definition: <String, Object?>{
      'type': 'object',
      'properties': <String, Object?>{
        'answer': <String, Object?>{'type': 'string'},
        'days': <String, Object?>{
          'type': 'array',
          'items': <String, Object?>{'type': 'string'},
        },
      },
      'required': ['answer', 'days'],
    },
    dependencies: [],
  );
}
