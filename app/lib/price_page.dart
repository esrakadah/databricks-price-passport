import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:price_passport_app/berlin_time.dart';
import 'package:price_passport_app/prices.dart';

enum _Day { today, tomorrow }

class PricePage extends StatefulWidget {
  const PricePage({required this.api, required this.clock, super.key});

  final PriceApi api;
  final DateTime Function() clock;

  @override
  State<PricePage> createState() => _PricePageState();
}

class _PricePageState extends State<PricePage> {
  _Day _day = _Day.tomorrow;
  late Future<DayPrices> _prices;
  HourPrice? _selected;

  String get _deliveryDay {
    final now = widget.clock();
    return berlinDay(_day == _Day.today ? now : now.add(const Duration(days: 1)));
  }

  /// The request can fail before the next frame subscribes to it; `ignore` keeps that from counting as uncaught, while
  /// the FutureBuilder still receives and shows the error.
  Future<DayPrices> _fetch() => widget.api.day(_deliveryDay)..ignore();

  @override
  void initState() {
    super.initState();
    _prices = _fetch();
  }

  void _show(_Day day) => setState(() {
    _day = day;
    _selected = null;
    _prices = _fetch();
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Price Passport')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            'Hourly energy prices for Germany, from a versioned model on Databricks.',
            style: Theme.of(context).textTheme.bodyLarge,
          ),
          const SizedBox(height: 16),
          SegmentedButton<_Day>(
            segments: const [
              ButtonSegment(value: _Day.today, label: Text('Today')),
              ButtonSegment(value: _Day.tomorrow, label: Text('Tomorrow')),
            ],
            selected: {_day},
            onSelectionChanged: (selection) => _show(selection.single),
          ),
          const SizedBox(height: 16),
          FutureBuilder<DayPrices>(
            future: _prices,
            builder: (context, snapshot) {
              if (snapshot.hasError) return Text('${snapshot.error}');
              final prices = snapshot.data;
              if (prices == null) return const Center(child: CircularProgressIndicator());
              if (prices.hours.isEmpty) return Text('No prices published for ${prices.deliveryDay} yet.');
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SourceBadge(prices: prices, now: widget.clock()),
                  const SizedBox(height: 12),
                  PriceChart(hours: prices.hours, onHourTapped: (hour) => setState(() => _selected = hour)),
                  const SizedBox(height: 12),
                  if (_selected case final hour?) HourDetails(hour: hour),
                ],
              );
            },
          ),
          const SizedBox(height: 24),
          const Attribution(),
        ],
      ),
    );
  }
}

/// Says where the numbers come from, and how old they are when they come from the snapshot.
class SourceBadge extends StatelessWidget {
  const SourceBadge({required this.prices, required this.now, super.key});

  final DayPrices prices;
  final DateTime now;

  @override
  Widget build(BuildContext context) {
    final age = now.difference(prices.fetchedAt);
    final label = prices.isLive
        ? 'Live from Databricks'
        : 'Snapshot from ${berlinDay(prices.fetchedAt)} ${berlinHourLabel(prices.fetchedAt)}, ${age.inHours} h old';
    return Chip(
      avatar: Icon(prices.isLive ? Icons.bolt : Icons.history, size: 18),
      label: Text(label),
    );
  }
}

/// One bar per hour, below the zero line when the price is negative. Tapping a bar reports its hour.
class PriceChart extends StatelessWidget {
  const PriceChart({required this.hours, required this.onHourTapped, super.key});

  static const height = 220.0;

  final List<HourPrice> hours;
  final ValueChanged<HourPrice> onHourTapped;

  @override
  Widget build(BuildContext context) {
    final prices = hours.map((hour) => hour.priceEurMwh);
    final summary =
        '${hours.length} hourly prices from ${prices.reduce(math.min).toStringAsFixed(2)} '
        'to ${prices.reduce(math.max).toStringAsFixed(2)} EUR per MWh';
    return Semantics(
      label: summary,
      child: LayoutBuilder(
        builder: (context, constraints) => GestureDetector(
          onTapDown: (details) {
            final index = (details.localPosition.dx / constraints.maxWidth * hours.length).floor();
            onHourTapped(hours[index.clamp(0, hours.length - 1)]);
          },
          child: CustomPaint(
            size: Size(constraints.maxWidth, height),
            painter: _BarsPainter(hours, Theme.of(context).colorScheme),
          ),
        ),
      ),
    );
  }
}

class _BarsPainter extends CustomPainter {
  _BarsPainter(this.hours, this.colors);

  static const _gapFraction = 0.2;

  final List<HourPrice> hours;
  final ColorScheme colors;

  @override
  void paint(Canvas canvas, Size size) {
    final prices = hours.map((hour) => hour.priceEurMwh).toList();
    final top = math.max(0, prices.reduce(math.max));
    final bottom = math.min(0, prices.reduce(math.min));
    final span = top - bottom == 0 ? 1 : top - bottom;
    final zeroY = size.height * top / span;
    final slot = size.width / hours.length;
    for (final (index, hour) in hours.indexed) {
      final barTop = size.height * (top - math.max(0, hour.priceEurMwh)) / span;
      final barBottom = size.height * (top - math.min(0, hour.priceEurMwh)) / span;
      final paint = Paint()
        ..color = hour.priceEurMwh < 0 ? colors.tertiary : colors.primary.withValues(alpha: hour.complete ? 1 : 0.4);
      canvas.drawRect(
        Rect.fromLTRB(
          index * slot + slot * _gapFraction / 2,
          barTop,
          (index + 1) * slot - slot * _gapFraction / 2,
          barBottom,
        ),
        paint,
      );
    }
    canvas.drawLine(Offset(0, zeroY), Offset(size.width, zeroY), Paint()..color = colors.outline);
  }

  @override
  bool shouldRepaint(_BarsPainter oldDelegate) => oldDelegate.hours != hours || oldDelegate.colors != colors;
}

class HourDetails extends StatelessWidget {
  const HourDetails({required this.hour, super.key});

  final HourPrice hour;

  @override
  Widget build(BuildContext context) {
    final start = berlinHourLabel(hour.hourStart);
    final end = berlinHourLabel(hour.hourStart.add(const Duration(hours: 1)));
    return Card(
      child: ListTile(
        title: Text('$start to $end Berlin time'),
        subtitle: Text(
          '${hour.priceEurMwh.toStringAsFixed(2)} EUR/MWh, ${hour.priceCentPerKwh.toStringAsFixed(2)} ct/kWh wholesale'
          '${hour.complete ? '' : ', some quarter-hours missing'}',
        ),
      ),
    );
  }
}

class Attribution extends StatelessWidget {
  const Attribution({super.key});

  @override
  Widget build(BuildContext context) {
    return Text(
      'Day-ahead prices: Bundesnetzagentur | SMARD.de via Energy-Charts (Fraunhofer ISE), CC BY 4.0. '
      'Weather: Open-Meteo, CC BY 4.0. 15-minute prices are averaged into hours. '
      'A demonstration, not an offer or a forecast to rely on.',
      style: Theme.of(context).textTheme.bodySmall,
    );
  }
}
