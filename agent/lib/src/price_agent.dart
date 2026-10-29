import 'package:genkit/genkit.dart';
import 'package:genkit_mcp/genkit_mcp.dart';
import 'package:logging/logging.dart';
import 'package:price_passport_agent/src/schemas.dart';

/// The Gemini model the agent runs on, in one place.
const defaultModelId = 'gemini-3.5-flash-lite';

/// A model call plus tool round trips; enough for "look up tomorrow and today, then compare".
const maxAgentTurns = 4;

const _systemPrompt =
    'You explain hourly day-ahead electricity prices for Germany from the Price Passport demo. Look the day up with '
    'the lookup tool before you say anything about a price, and use only the numbers it returns: compare the hour '
    'with the mean, the cheapest and the dearest hour, and say what negative prices mean when there are any. Say '
    'whether the numbers are live or from a snapshot. Never claim which model, model version or training data '
    'produced a price: the tool says that lineage is not available yet, so say so if you are asked. If the tool '
    'finds nothing, say so. Answer in the language of the question, in two to four sentences, and list every day you '
    'looked up in days.';

final _log = Logger('price_agent');

/// `explainPrice`: a Genkit flow whose only knowledge of prices comes through the MCP tool.
class PriceAgent {
  PriceAgent._(this.flow, this._mcpClient);

  final Flow<PriceQuestion, PriceAnswer, void, void> flow;
  final GenkitMcpClient _mcpClient;

  static Future<PriceAgent> connect({
    required Genkit ai,
    required Uri mcpUrl,
    required ModelRef<dynamic> model,
  }) async {
    final mcpClient = createMcpClient(
      McpClientOptions(
        name: 'price-agent',
        mcpServer: McpServerConfig(url: mcpUrl),
      ),
    );
    await mcpClient.ready();
    final tools = await mcpClient.getActiveTools(ai);

    final flow = ai.defineFlow<PriceQuestion, PriceAnswer, void, void>(
      name: 'explainPrice',
      inputSchema: PriceQuestion.$schema,
      outputSchema: PriceAnswer.$schema,
      fn: (input, _) async {
        try {
          final response = await ai.generate(
            model: model,
            system: _systemPrompt,
            prompt: input.question,
            tools: tools,
            maxTurns: maxAgentTurns,
            outputSchema: PriceAnswer.$schema,
          );
          final answer = response.output;
          if (answer == null) {
            throw StateError(
              'The model returned no structured answer (finish ${response.finishReason}: '
              '${response.finishMessage ?? 'no message'}): ${response.text}',
            );
          }
          return answer;
        } on Object catch (error, stackTrace) {
          _log.severe('explainPrice failed for "${input.question}"', error, stackTrace);
          rethrow;
        }
      },
    );
    return PriceAgent._(flow, mcpClient);
  }

  Future<void> close() => _mcpClient.close();
}
