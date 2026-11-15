"""Copy Plotly's bundled browser library so charts work without a CDN."""
from pathlib import Path
from plotly.offline import get_plotlyjs

target = Path(__file__).resolve().parents[1] / "static" / "plotly.min.js"
target.parent.mkdir(exist_ok=True)
target.write_text(get_plotlyjs(), encoding="utf-8")
print(f"Saved {target.name}; charts can run offline.")
