"""Pure-Python Code 128 (set B) barcode as inline SVG, for print formats.

Usage in Jinja: {{ code128_svg(doc.name, height=40) }}
"""

# Bar/space module widths for symbol values 0..105 (103-105 are start codes)
_W = (
	"212222 222122 222221 121223 121322 131222 122213 122312 132212 221213 221312 231212 112232 122132 "
	"122231 113222 123122 123221 223211 221132 221231 213212 223112 312131 311222 321122 321221 312212 "
	"322112 322211 212123 212321 232121 111323 131123 131321 112313 132113 132311 211313 231113 231311 "
	"112133 112331 132131 113123 113321 133121 313121 211331 231131 213113 213311 213131 311123 311321 "
	"331121 312113 312311 332111 314111 221411 431111 111224 111422 121124 121421 141122 141221 112214 "
	"112412 122114 122411 142112 142211 241211 221114 413111 241112 134111 111242 121142 121241 114212 "
	"124112 124211 411212 421112 421211 212141 214121 412121 111143 111341 131141 114113 114311 411113 "
	"411311 113141 114131 311141 411131 211412 211214 211232"
).split()
_STOP = "2331112"
_START_B = 104


def _symbols(text):
	values = [_START_B]
	for ch in str(text):
		code = ord(ch)
		if code < 32 or code > 127:
			code = ord("?")
		values.append(code - 32)
	checksum = values[0]
	for i, v in enumerate(values[1:], start=1):
		checksum += i * v
	values.append(checksum % 103)
	return values


def code128_svg(text, height=40, module=1.6, quiet=10, show_text=False):
	"""Return an <svg> element string for the given text."""
	pattern = "".join(_W[v] for v in _symbols(text)) + _STOP
	x = quiet
	rects = []
	bar = True
	for w in pattern:
		width = int(w) * module
		if bar:
			rects.append(f'<rect x="{x:.2f}" y="0" width="{width:.2f}" height="{height}"/>')
		x += width
		bar = not bar
	total = x + quiet
	text_h = 14 if show_text else 0
	label = ""
	if show_text:
		safe = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
		label = (f'<text x="{total / 2:.2f}" y="{height + 12}" font-size="12" text-anchor="middle" '
			f'font-family="monospace">{safe}</text>')
	return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{total:.2f}" height="{height + text_h}" '
		f'viewBox="0 0 {total:.2f} {height + text_h}"><rect width="100%" height="100%" fill="#fff"/>'
		f'<g fill="#000">{"".join(rects)}</g>{label}</svg>')
