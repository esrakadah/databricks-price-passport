import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:logging/logging.dart';
import 'package:price_passport_api/price_passport_api.dart';
import 'package:shelf/shelf.dart';
import 'package:shelf/shelf_io.dart' as io;

/// Cloud Run sets `PORT`; locally it falls back to the same 8080.
const _defaultPort = 8080;

/// Configuration comes from the environment; on Cloud Run the client secret comes from Secret Manager.
String _required(String name) {
  final value = Platform.environment[name];
  if (value == null || value.isEmpty) throw StateError('$name is not set');
  return value;
}

Future<void> main() async {
  Logger.root.level = Level.INFO;
  Logger.root.onRecord.listen((record) {
    stderr.writeln(
      '${record.level.name} ${record.loggerName}: ${record.message}',
    );
    if (record.error != null) stderr.writeln('  ${record.error}');
  });

  final client = http.Client();
  DateTime clock() => DateTime.now().toUtc();
  final host = Uri.parse(_required('DATABRICKS_HOST'));
  final tokens = OAuthTokenSource(
    ServicePrincipal(
      host: host,
      clientId: _required('DATABRICKS_CLIENT_ID'),
      clientSecret: _required('DATABRICKS_CLIENT_SECRET'),
    ),
    client: client,
    clock: clock,
  );
  final sql = SqlStatementClient(
    host: host,
    warehouseId: _required('DATABRICKS_WAREHOUSE_ID'),
    tokens: tokens,
    client: client,
    clock: clock,
  );
  var live = DatabricksPriceSource(
    sql,
    catalog: _required('PRICE_PASSPORT_CATALOG'),
    schema: _required('PRICE_PASSPORT_SCHEMA'),
    clock: clock,
  ).deliveryDay;
  final snapshotBucket = Platform.environment['SNAPSHOT_BUCKET'];
  if (snapshotBucket != null && snapshotBucket.isNotEmpty) {
    final metadataTokens = MetadataTokenSource(client: client, clock: clock);
    live = withSnapshotFallback(
      live,
      CloudStorageSnapshots(
        bucket: snapshotBucket,
        client: client,
        token: metadataTokens.token,
      ),
    );
  }
  final prices = CachedPriceSource(live, clock: clock).deliveryDay;

  final handler = const Pipeline().addMiddleware(logRequests()).addHandler(priceRoutes(prices).call);
  final port = int.tryParse(Platform.environment['PORT'] ?? '') ?? _defaultPort;
  final server = await io.serve(handler, InternetAddress.anyIPv4, port);
  stderr.writeln('price passport api on port ${server.port}');
}
