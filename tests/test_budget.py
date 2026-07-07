from wayfarer.engine.budget import assemble_budget, fits


def test_assemble_and_total():
    b = assemble_budget(flights=1200, nightly_rate=140, nights=7,
                        per_diem_pp_per_day=80, pax=2, buffer_pct=0.10)
    assert b.lodging == 980          # 140 * 7
    assert b.per_diem == 1120        # 80 * 2 * 7
    # subtotal 1200+980+1120 = 3300, buffer 330, total 3630
    assert b.total == 3630.0


def test_fits_respects_margin():
    b = assemble_budget(flights=800, nightly_rate=80, nights=7,
                        per_diem_pp_per_day=45, pax=2, buffer_pct=0.10)
    # subtotal 800+560+630=1990, buffer 199, total 2189
    assert fits(b, ceiling=3000, margin=0.10) is True
    assert fits(b, ceiling=2200, margin=0.10) is False  # 2200*0.9=1980 < 2189
