from wayfarer.engine.frames import ffmpeg_cmd


def test_ffmpeg_cmd_has_mpdecimate_and_paths():
    cmd = ffmpeg_cmd("in.mov", "out/frame_%04d.png", fps=2)
    assert cmd[0] == "ffmpeg"
    assert "in.mov" in cmd
    assert "out/frame_%04d.png" in cmd
    # mpdecimate + fps in the filter chain, vfr sync
    joined = " ".join(cmd)
    assert "mpdecimate" in joined and "fps=2" in joined
    assert "vfr" in joined


def test_ffmpeg_cmd_has_overwrite_flag():
    cmd = ffmpeg_cmd("in.mov", "out/frame_%04d.png", fps=2)
    assert "-y" in cmd, "ffmpeg must receive -y so re-runs overwrite without prompting"
