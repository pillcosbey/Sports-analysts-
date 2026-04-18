"""Tests for the backtest engine."""

from app.backtest.engine import generate_synthetic_history, run_backtest


class TestBacktest:
    def test_generates_correct_count(self):
        h = generate_synthetic_history(n_games=100)
        assert len(h) == 100

    def test_history_has_required_fields(self):
        h = generate_synthetic_history(n_games=10)
        for g in h:
            assert g.sport in ("nba", "mlb")
            assert g.player
            assert g.stat
            assert g.actual >= 0

    def test_backtest_runs_and_returns_report(self):
        h = generate_synthetic_history(n_games=100)
        report = run_backtest(h, min_edge_pct=3.0, sim_trials=500)
        assert report.total_games == 100
        assert report.wins + report.losses + report.pushes <= report.picks_made
        assert 0.0 <= report.win_rate <= 1.0

    def test_backtest_by_sport_populated(self):
        h = generate_synthetic_history(n_games=200)
        report = run_backtest(h, min_edge_pct=2.0, sim_trials=500)
        assert "nba" in report.by_sport or "mlb" in report.by_sport

    def test_calibration_bins(self):
        h = generate_synthetic_history(n_games=200)
        report = run_backtest(h, min_edge_pct=0.0, sim_trials=500)
        assert len(report.calibration) > 0
        for c in report.calibration:
            assert "bin" in c
            assert 0 <= c["predicted"] <= 1
            assert 0 <= c["actual"] <= 1

    def test_zero_edge_threshold_makes_more_picks(self):
        h = generate_synthetic_history(n_games=100, seed=42)
        r1 = run_backtest(h, min_edge_pct=0.0, sim_trials=500)
        r2 = run_backtest(h, min_edge_pct=10.0, sim_trials=500)
        assert r1.picks_made >= r2.picks_made
