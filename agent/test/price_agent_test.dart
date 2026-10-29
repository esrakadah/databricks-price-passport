import 'dart:convert';

import 'package:genkit/genkit.dart';
import 'package:genkit_mcp/genkit_mcp.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:price_passport_agent/price_passport_agent.dart';
import 'package:test/test.dart';

/// 30 Oct 2026, Berlin winter time: 00:00 Berlin is 23:00 UTC the day before.
final _firstHour = DateTime.utc(2026, 10, 29, 23);
const _hoursPerDay = 24;

http.Client _api({List<double>? prices, bool lastIncomplete = false, int status = 200}) => MockClient((request) async {
  if (status != 200) return http.Response('{"error": "unavailable"}', status);
  final dayPrices = prices ?? List<double>.generate(_hoursPerDay, (hour) => hour == 13 ? -5.0 : 100.0 + hour);
  return http.Response(
    jsonEncode({
      'delivery_day': request.url.queryParameters['day'],
      'source': 'live',
      'fetched_at': '2026-10-29T12:00:00.000Z',
      'hours': [
        for (final (index, price) in dayPrices.indexed)
          {
            'hour_start': _firstHour.add(Duration(hours: index)).toIso8601String(),
            'price_eur_mwh': price,
            'complete': !(lastIncomplete && index == dayPrices.length - 1),
          },
      ],
    }),
    200,
  );
});

DayPriceDescriber _describer(http.Client client) =>
    DayPriceDescriber(apiBase: Uri.parse('https://api.example'), client: client);

/// A fake model that calls the lookup tool for [day], then answers with whatever the tool returned.
Model<dynamic> _scriptedModel(Genkit ai, {required String day, required void Function(String) onToolOutput}) =>
    ai.defineModel(
      name: 'fake-explainer',
      fn: (request, _) async {
        final last = request.messages.last;
        if (last.role == Role.tool) {
          final toolOutput = '${last.content.first.toolResponse?.output}';
          onToolOutput(toolOutput);
          return ModelResponse(
            finishReason: FinishReason.stop,
            message: Message(
              role: Role.model,
              content: [
                TextPart(
                  text: jsonEncode({
                    'answer': toolOutput,
                    'days': [day],
                  }),
                ),
              ],
            ),
          );
        }
        final tool = request.tools!.singleWhere((tool) => tool.name.endsWith(lookupDayPricesToolName));
        return ModelResponse(
          finishReason: FinishReason.stop,
          message: Message(
            role: Role.model,
            content: [
              ToolRequestPart(
                toolRequest: ToolRequest(name: tool.name, input: {'day': day}),
              ),
            ],
          ),
        );
      },
    );

void main() {
  group('DayPriceDescriber', () {
    test('describes the day in Berlin time with the facts an explanation starts from', () async {
      final description =
          jsonDecode(await _describer(_api(lastIncomplete: true)).describe('2026-10-30')) as Map<String, dynamic>;

      expect(description['source'], 'live');
      expect(description['cheapestHour'], {'hour': '13:00', 'price': -5.0});
      expect(description['dearestHour'], {'hour': '23:00', 'price': 123.0});
      expect(description['negativeHours'], ['13:00']);
      expect(description['incompleteHours'], ['23:00']);
      expect((description['hours'] as Map<String, dynamic>)['00:00'], 100.0);
      expect(description['lineage'], contains('not available yet'));
    });

    test('says plainly when the API has no prices', () async {
      expect(
        await _describer(_api(status: 503)).describe('2026-10-30'),
        'Prices for 2026-10-30 are not available right now.',
      );
      expect(await _describer(_api(prices: [])).describe('2026-10-31'), 'No prices are published for 2026-10-31 yet.');
    });
  });

  group('over MCP', () {
    late PricesMcpServer mcpServer;

    setUp(() async => mcpServer = await PricesMcpServer.start(_describer(_api())));
    tearDown(() => mcpServer.close());

    test('an MCP client finds lookup_day_prices and reads a day through it', () async {
      final client = createMcpClient(
        McpClientOptions(
          name: 'test-client',
          mcpServer: McpServerConfig(url: mcpServer.url),
        ),
      );
      addTearDown(client.close);
      await client.ready();

      final tools = await client.getActiveTools(Genkit());
      final lookup = tools.singleWhere((tool) => tool.name.endsWith(lookupDayPricesToolName));
      final output = '${(await lookup.call({'day': '2026-10-30'})).output}';

      expect(jsonDecode(output), containsPair('day', '2026-10-30'));
    });

    test('the flow answers only from what the tool returned', () async {
      final ai = Genkit();
      String? toolOutput;
      final agent = await PriceAgent.connect(
        ai: ai,
        mcpUrl: mcpServer.url,
        model: modelRef(
          _scriptedModel(ai, day: '2026-10-30', onToolOutput: (output) => toolOutput = output).name,
        ),
      );
      addTearDown(agent.close);

      final answer = await agent.flow(PriceQuestion(question: 'Why is 23:00 tomorrow the dearest hour?'));

      expect(toolOutput, isNotNull);
      expect(answer.answer, toolOutput);
      expect(answer.days, ['2026-10-30']);
    });
  });
}
