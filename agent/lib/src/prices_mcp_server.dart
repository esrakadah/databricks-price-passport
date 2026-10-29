import 'dart:convert';
import 'dart:io';

import 'package:genkit/genkit.dart';
import 'package:genkit_mcp/genkit_mcp.dart';
import 'package:http/http.dart' as http;
import 'package:price_passport_agent/src/berlin_time.dart';
import 'package:price_passport_agent/src/schemas.dart';

/// The MCP tool name. MCP clients see it as `price-passport/lookup_day_prices`.
const lookupDayPricesToolName = 'lookup_day_prices';

/// Reads one delivery day from the Price Passport API and describes it for the model: every hour in Berlin time, plus
/// the facts a good explanation starts from, so the model compares numbers instead of guessing them.
class DayPriceDescriber {
  DayPriceDescriber({required this._apiBase, required this._client});

  final Uri _apiBase;
  final http.Client _client;

  Future<String> describe(String day) async {
    final response = await _client.get(_apiBase.replace(path: '/prices', queryParameters: {'day': day}));
    if (response.statusCode != HttpStatus.ok) return 'Prices for $day are not available right now.';
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    final hours = [
      for (final hour in body['hours'] as List<dynamic>)
        (
          label: berlinHourLabel(DateTime.parse((hour as Map<String, dynamic>)['hour_start'] as String)),
          price: (hour['price_eur_mwh'] as num).toDouble(),
          complete: hour['complete'] as bool,
        ),
    ];
    if (hours.isEmpty) return 'No prices are published for $day yet.';
    final cheapest = hours.reduce((a, b) => a.price <= b.price ? a : b);
    final dearest = hours.reduce((a, b) => a.price >= b.price ? a : b);
    final mean = hours.map((hour) => hour.price).reduce((a, b) => a + b) / hours.length;
    return jsonEncode({
      'day': day,
      'source': body['source'],
      'fetchedAt': body['fetched_at'],
      'unit': 'EUR/MWh, day-ahead wholesale price for Germany and Luxembourg',
      'mean': _rounded(mean),
      'cheapestHour': {'hour': cheapest.label, 'price': _rounded(cheapest.price)},
      'dearestHour': {'hour': dearest.label, 'price': _rounded(dearest.price)},
      'negativeHours': [for (final hour in hours.where((hour) => hour.price < 0)) hour.label],
      'incompleteHours': [for (final hour in hours.where((hour) => !hour.complete)) hour.label],
      'hours': {for (final hour in hours) hour.label: _rounded(hour.price)},
      'lineage': 'not available yet: model version and training data are added once scoring is built',
    });
  }

  static double _rounded(double value) => (value * _centsPerEuro).round() / _centsPerEuro;
  static const _centsPerEuro = 100;
}

/// The Price Passport data as an MCP server over Streamable HTTP on loopback, so the agent, an IDE or another agent
/// reads prices the same way.
class PricesMcpServer {
  PricesMcpServer._(this._server, this._transport);

  final GenkitMcpServer _server;
  final StreamableHttpServerTransport _transport;

  Uri get url => Uri.parse('http://${_transport.address.address}:${_transport.port}/mcp');

  /// Port 0 picks a free one, which keeps the server private inside the container.
  static Future<PricesMcpServer> start(DayPriceDescriber describer, {int port = 0}) async {
    final ai = Genkit();
    ai.defineTool<DayLookup, String>(
      name: lookupDayPricesToolName,
      description:
          'Looks up the hourly day-ahead prices of one delivery day in Berlin time and returns them as JSON, with '
          'the mean, the cheapest and dearest hour, negative and incomplete hours, and whether the numbers are live '
          'or from a snapshot.',
      inputSchema: DayLookup.$schema,
      fn: (input, _) async => .response(await describer.describe(input.day)),
    );
    final server = createMcpServer(ai, McpServerOptions(name: 'price-passport', version: '0.1.0'));
    final transport = await StreamableHttpServerTransport.bind(address: InternetAddress.loopbackIPv4, port: port);
    await server.start(transport);
    return PricesMcpServer._(server, transport);
  }

  Future<void> close() async {
    await _server.close();
    await _transport.close();
  }
}
