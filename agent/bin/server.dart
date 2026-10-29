import 'dart:io';

import 'package:genkit/genkit.dart';
import 'package:genkit/io.dart';
import 'package:genkit_google_genai/genkit_google_genai.dart';
import 'package:genkit_shelf/genkit_shelf.dart';
import 'package:http/http.dart' as http;
import 'package:logging/logging.dart';
import 'package:price_passport_agent/price_passport_agent.dart';
import 'package:shelf/shelf.dart';
import 'package:shelf/shelf_io.dart' as io;
import 'package:shelf_router/shelf_router.dart';

/// Cloud Run sets `PORT`; locally it falls back to 8081, next to the API on 8080.
const _defaultPort = 8081;

/// Origins the web app may call from, comma separated in `ALLOWED_ORIGINS`; the app is served by the API, on another
/// origin. CORS is no access control: any non-browser client can still call the flow.
List<String> _allowedOrigins() =>
    (Platform.environment['ALLOWED_ORIGINS'] ?? '*').split(',').map((origin) => origin.trim()).toList();

/// Starts the prices MCP server on loopback, connects the agent to it and serves `POST /explainPrice`. The prices come
/// from the API at `PRICE_PASSPORT_API_URL`; the Gemini key from `GEMINI_API_KEY` (on Cloud Run, Secret Manager).
Future<void> main() async {
  Logger.root.level = Level.INFO;
  Logger.root.onRecord.listen((record) {
    stderr.writeln('${record.level.name} ${record.loggerName}: ${record.message}');
    if (record.error != null) stderr.writeln('  ${record.error}');
  });
  final apiUrl = Platform.environment['PRICE_PASSPORT_API_URL'];
  if (apiUrl == null || apiUrl.isEmpty) throw StateError('PRICE_PASSPORT_API_URL is not set');
  final port = int.tryParse(Platform.environment['PORT'] ?? '') ?? _defaultPort;
  final modelId = Platform.environment['GEMINI_MODEL'] ?? defaultModelId;

  final mcpServer = await PricesMcpServer.start(DayPriceDescriber(apiBase: Uri.parse(apiUrl), client: http.Client()));
  final ai = Genkit(plugins: [googleAI()]);
  final agent = await PriceAgent.connect(ai: ai, mcpUrl: mcpServer.url, model: googleAI.gemini(modelId));

  final flows = GenkitRouter()..addAction(agent.flow);
  // Not /healthz: Cloud Run's front end reserves paths ending in "z" and never forwards them to the container.
  final health = Router()..get('/health', (Request _) => Response.ok('ok'));
  final handler = const Pipeline()
      .addMiddleware(logRequests())
      .addHandler(
        Cascade()
            .add(health.call)
            .add(flows.asShelfHandler(cors: CorsOptions(allowedOrigins: _allowedOrigins())))
            .handler,
      );
  final server = await io.serve(handler, InternetAddress.anyIPv4, port);
  stderr.writeln('explainPrice on port ${server.port} (model $modelId, MCP at ${mcpServer.url})');

  ProcessSignal.sigterm.watch().listen((_) async {
    await server.close();
    await agent.close();
    await mcpServer.close();
    exit(0);
  });
}
