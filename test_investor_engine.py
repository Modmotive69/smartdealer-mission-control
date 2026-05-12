"""
Unit tests for investor_engine aggregation logic in server.py.

Run: python3 mission_control/test_investor_engine.py
No network. Patches Alpaca calls + reads live signal files on disk.
"""
import sys
import os
import json
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))

# Stub the Alpaca env loader so tests are deterministic
import server  # noqa: E402


class InvestorEngineTests(unittest.TestCase):

    def setUp(self):
        # Clear cache between tests
        server._IE_CACHE.clear()

    def test_signal_block_handles_missing_file(self):
        block = server._signal_block(
            server.FORECASTER_DIR / 'NONEXISTENT.json', 5.0, 'X', '?'
        )
        self.assertEqual(block['ticker_count'], 0)
        self.assertEqual(block['above_threshold'], 0)
        self.assertEqual(block['top_3'], [])
        self.assertEqual(block['threshold'], 5.0)
        self.assertEqual(block['emoji'], '?')

    def test_signal_block_real_forecaster(self):
        block = server._signal_block(
            server.FORECASTER_DIR / 'latest.json', 5.0, 'Forecaster', '🧠'
        )
        self.assertGreater(block['ticker_count'], 0,
                           'forecaster latest.json should have tickers')
        self.assertIn('top_3', block)
        self.assertGreaterEqual(block['above_threshold'], 0)

    def test_candidates_excludes_universe_members(self):
        cand = server._ie_build_candidates()
        universe_size = cand['universe_size']
        self.assertGreater(universe_size, 0, 'wheel universe must be set')
        for row in cand['candidates_to_join']:
            self.assertFalse(
                row['in_universe'],
                f"Candidate {row['symbol']} should NOT be in universe"
            )

    def test_candidates_sorted_desc(self):
        cand = server._ie_build_candidates()
        scores = [r['score'] for r in cand['candidates_to_join']]
        self.assertEqual(scores, sorted(scores, reverse=True),
                         'candidates must be score-desc')

    def test_top10_composite_has_components(self):
        cand = server._ie_build_candidates()
        top = cand['top_10_composite']
        self.assertEqual(len(top), 10)
        for row in top:
            self.assertIn('components', row)
            self.assertIsInstance(row['components'], dict)
            self.assertIn('in_universe', row)

    def test_cache_ttl_returns_same_object(self):
        calls = {'n': 0}

        def builder():
            calls['n'] += 1
            return {'count': calls['n']}

        a = server._ie_cache_get('test_key', 60, builder)
        b = server._ie_cache_get('test_key', 60, builder)
        self.assertEqual(a, b)
        self.assertEqual(calls['n'], 1, 'builder should only run once within TTL')

    def test_cache_ttl_expires(self):
        calls = {'n': 0}

        def builder():
            calls['n'] += 1
            return {'count': calls['n']}

        server._ie_cache_get('exp_key', 0, builder)
        # TTL=0 means expire immediately
        import time as _t
        _t.sleep(0.01)
        server._ie_cache_get('exp_key', 0, builder)
        self.assertEqual(calls['n'], 2)

    def test_insights_returns_array(self):
        # Patch Alpaca to keep test offline-ish
        with patch.object(server, '_alpaca_req', return_value={}):
            data = server._ie_build_insights()
        self.assertIn('insights', data)
        self.assertIsInstance(data['insights'], list)
        self.assertGreaterEqual(len(data['insights']), 1)
        for s in data['insights']:
            self.assertIsInstance(s, str)
            self.assertGreater(len(s), 0)

    def test_composite_payload_shape(self):
        with patch.object(server, '_alpaca_req', return_value={}):
            payload = server._ie_build_composite()
        for key in ('wheel_summary', 'signal_health', 'backtests',
                    'forecaster', 'candidates', 'alpaca', 'insights',
                    'activity', 'wheel_config', 'generated_at'):
            self.assertIn(key, payload, f'composite missing key: {key}')

        # Signal health must have 4 sources
        sh = payload['signal_health']
        self.assertEqual(
            set(sh.keys()),
            {'politician', 'top_trader', 'news', 'analyst'}
        )

    def test_alpaca_underlying_strips_occ(self):
        # Verify the OCC-stripping regex inside _ie_build_alpaca
        # by exercising it indirectly via positions stub
        fake_positions = [
            {'symbol': 'KO260618P00077500', 'qty': '-1',
             'market_value': '-99', 'unrealized_pl': '-4',
             'unrealized_plpc': '-0.04', 'avg_entry_price': '0.95',
             'current_price': '0.99', 'cost_basis': '-95',
             'side': 'short'},
        ]

        def fake_req(path, keys, base='https://paper-api.alpaca.markets'):
            if path == '/v2/account':
                return {'equity': '100000', 'last_equity': '100000',
                        'cash': '100000', 'options_buying_power': '90000',
                        'buying_power': '180000', 'portfolio_value': '100000',
                        'status': 'ACTIVE', 'account_number': 'PA000'}
            if path == '/v2/positions':
                return fake_positions
            if path.startswith('/v2/orders'):
                return []
            if path == '/v2/clock':
                return {'is_open': True, 'next_open': '', 'next_close': ''}
            return {}

        with patch.object(server, '_alpaca_req', side_effect=fake_req):
            data = server._ie_build_alpaca()
        self.assertEqual(data['positions_count'], 1)
        self.assertEqual(data['positions'][0]['underlying'], 'KO')
        self.assertIn('Consumer Staples', data['sector_market_value'])


    def test_walk_pnl_sell_then_buy_close_is_realized(self):
        trades = [
            {'action': 'submitted', 'occ_symbol': 'KO260618P00077500',
             'symbol': 'KO',
             'payload': {'ticket': {'side': 'sell_to_open', 'qty': 1,
                                    'limit_price': 0.95, 'occ_symbol': 'KO260618P00077500'}},
             'timestamp_utc': '2026-05-12T16:00:00Z'},
            {'action': 'submitted', 'occ_symbol': 'KO260618P00077500',
             'symbol': 'KO',
             'payload': {'ticket': {'side': 'buy_to_close', 'qty': 1,
                                    'limit_price': 0.30, 'occ_symbol': 'KO260618P00077500'}},
             'timestamp_utc': '2026-06-01T16:00:00Z'},
        ]
        r = server._walk_wheel_trades_for_pnl(trades=trades)
        # credit 95, debit 30 → realized 65, premium_gross 95, premium_net 65, spend 30
        self.assertAlmostEqual(r['premium_gross'], 95.0)
        self.assertAlmostEqual(r['premium_net'], 65.0)
        self.assertAlmostEqual(r['spend'], 30.0)
        self.assertAlmostEqual(r['realized'], 65.0)
        self.assertEqual(r['wins'], 1)
        self.assertEqual(r['losses'], 0)
        self.assertEqual(len(r['closed_cycles']), 1)
        cycle = r['closed_cycles'][0]
        self.assertEqual(cycle['outcome'], 'closed_for_profit')
        self.assertAlmostEqual(cycle['realized_pnl'], 65.0)

    def test_walk_pnl_expired_keeps_full_credit(self):
        trades = [
            {'action': 'submitted', 'occ_symbol': 'PG260618P00135000',
             'symbol': 'PG',
             'payload': {'ticket': {'side': 'sell_to_open', 'qty': 1,
                                    'limit_price': 1.06, 'occ_symbol': 'PG260618P00135000'}},
             'timestamp_utc': '2026-05-12T13:12:00Z'},
            {'action': 'expired_otm', 'occ_symbol': 'PG260618P00135000',
             'symbol': 'PG',
             'payload': {'ticket': {'occ_symbol': 'PG260618P00135000'}},
             'timestamp_utc': '2026-06-18T20:00:00Z'},
        ]
        r = server._walk_wheel_trades_for_pnl(trades=trades)
        self.assertAlmostEqual(r['realized'], 106.0)
        self.assertEqual(r['wins'], 1)
        self.assertEqual(r['open_legs_count'], 0)
        self.assertEqual(r['closed_cycles'][0]['outcome'], 'expired_otm')

    def test_walk_pnl_loss_cycle(self):
        trades = [
            {'action': 'submitted', 'occ_symbol': 'XYZ260618P00100000',
             'symbol': 'XYZ',
             'payload': {'ticket': {'side': 'sell_to_open', 'qty': 1,
                                    'limit_price': 1.00,
                                    'occ_symbol': 'XYZ260618P00100000'}},
             'timestamp_utc': '2026-05-12T13:00:00Z'},
            {'action': 'submitted', 'occ_symbol': 'XYZ260618P00100000',
             'symbol': 'XYZ',
             'payload': {'ticket': {'side': 'buy_to_close', 'qty': 1,
                                    'limit_price': 2.50,
                                    'occ_symbol': 'XYZ260618P00100000'}},
             'timestamp_utc': '2026-05-20T13:00:00Z'},
        ]
        r = server._walk_wheel_trades_for_pnl(trades=trades)
        # credit 100, debit 250 → realized -150, loss
        self.assertAlmostEqual(r['realized'], -150.0)
        self.assertEqual(r['wins'], 0)
        self.assertEqual(r['losses'], 1)
        self.assertEqual(r['closed_cycles'][0]['outcome'], 'closed_for_loss')

    def test_walk_pnl_skips_simulated(self):
        trades = [
            {'action': 'simulated', 'occ_symbol': 'X260618P00100000',
             'symbol': 'X',
             'payload': {'ticket': {'side': 'sell_to_open', 'qty': 1,
                                    'limit_price': 5.00,
                                    'occ_symbol': 'X260618P00100000'}},
             'timestamp_utc': '2026-05-12T13:00:00Z'},
        ]
        r = server._walk_wheel_trades_for_pnl(trades=trades)
        self.assertEqual(r['premium_gross'], 0.0)
        self.assertEqual(r['wins'], 0)
        self.assertEqual(r['open_legs_count'], 0)

    def test_walk_pnl_open_premium_at_risk(self):
        trades = [
            {'action': 'submitted', 'occ_symbol': 'WMT260618P00080000',
             'symbol': 'WMT',
             'payload': {'ticket': {'side': 'sell_to_open', 'qty': 2,
                                    'limit_price': 1.50,
                                    'occ_symbol': 'WMT260618P00080000'}},
             'timestamp_utc': '2026-05-12T13:00:00Z'},
        ]
        r = server._walk_wheel_trades_for_pnl(trades=trades)
        # 2 contracts × strike 80 × 100 = $16,000 at risk
        self.assertAlmostEqual(r['open_premium_at_risk'], 16000.0)
        self.assertAlmostEqual(r['premium_gross'], 300.0)
        self.assertEqual(r['open_legs_count'], 1)

    def test_pnl_periods_payload(self):
        with patch.object(server, '_alpaca_req', return_value={}):
            data = server._ie_build_pnl()
        for k in ('lifetime', 'ytd', 'mtd', 'by_month', 'by_year',
                  'by_account', 'closed_cycles', 'active_account_id'):
            self.assertIn(k, data)
        self.assertEqual(len(data['by_month']), 12, 'must return 12 monthly buckets')
        for m in data['by_month']:
            self.assertIn('period', m)
            self.assertRegex(m['period'], r'^\d{4}-\d{2}$')

    def test_account_ledger_loads(self):
        led = server._load_account_ledger()
        self.assertIn('accounts', led)
        self.assertIn('active_account_id', led)
        self.assertTrue(len(led['accounts']) >= 1)
        a = server._active_account()
        self.assertEqual(a.get('starting_capital'), 100000)

    def test_alpaca_payload_has_pnl_fields(self):
        def fake_req(path, keys, base='https://paper-api.alpaca.markets'):
            if path == '/v2/account':
                return {'equity': '99996', 'last_equity': '100000',
                        'cash': '100094', 'options_buying_power': '92344',
                        'buying_power': '184689', 'portfolio_value': '99996',
                        'status': 'ACTIVE', 'account_number': 'PA000'}
            if path == '/v2/positions':
                return []
            if path.startswith('/v2/orders'):
                return []
            if path == '/v2/clock':
                return {'is_open': True, 'next_open': '', 'next_close': ''}
            return {}

        with patch.object(server, '_alpaca_req', side_effect=fake_req):
            data = server._ie_build_alpaca()

        for f in ('starting_capital', 'total_pnl_dollars', 'total_pnl_pct',
                  'today_pnl_dollars', 'today_pnl_pct',
                  'realized_pnl', 'unrealized_pnl',
                  'open_premium_at_risk', 'premium_collected_gross',
                  'premium_collected_net'):
            self.assertIn(f, data, f'alpaca payload missing field: {f}')
        self.assertEqual(data['starting_capital'], 100000)
        self.assertAlmostEqual(data['total_pnl_dollars'], -4.0, places=1)

    def test_tax_export_csv_route(self):
        # Use Flask test client
        client = server.app.test_client()
        r = client.get('/api/investor_engine/tax_export/2026')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, 'text/csv')
        body = r.get_data(as_text=True)
        self.assertIn('symbol,occ_symbol,open_date', body)


if __name__ == '__main__':
    unittest.main(verbosity=2)
