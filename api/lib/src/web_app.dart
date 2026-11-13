import 'dart:io';

import 'package:price_passport_api/src/prices.dart';
import 'package:price_passport_api/src/routes.dart';
import 'package:shelf/shelf.dart';
import 'package:shelf_static/shelf_static.dart';

/// The API routes first; anything they do not answer is served from the built Flutter web app, if there is one. One
/// origin for both, so the app needs no CORS and there is one URL to share.
Handler appAndApi(PriceLookup prices, {required String webRoot}) {
  final api = priceRoutes(prices).call;
  if (!Directory(webRoot).existsSync()) return api;
  return Cascade().add(api).add(createStaticHandler(webRoot, defaultDocument: 'index.html')).handler;
}
