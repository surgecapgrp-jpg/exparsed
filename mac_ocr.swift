// Apple Vision text recognition for mac_ocr_server.py (compiled by it on first run).
//
// Worker protocol, one request per line on stdin, one JSON object per line on stdout:
//   <image path>                       recognize that image
//   pdf<TAB><path><TAB><page index>    draw that PDF page with PDFKit, then recognize it
//                                      (adds "pxPerPt" and "heightPt" for the page's points)
//   count<TAB><path>                   {"pages": n}
// A recognition result is:
//   {"w":px,"h":px,"secs":s,"skew":deg,"lines":[{"t":text,"a":other reading,"c":confidence,"x","y","w","h",
//     "words":[{"t","x","y","w","h"}]}],"sideways":n,"replaced":n,"added":n,"implausible":n}
// Coordinates are image pixels, top-left origin, with the page's skew removed (a scan fed
// in a degree or two crooked would otherwise drift a whole row up or down across the page,
// and the extractor groups text into rows by height on the page).
import Foundation
import Vision
import AppKit
import PDFKit

struct Quad { var cx: Double; var cy: Double; var w: Double; var h: Double; var angle: Double }

// VNRectangleObservation corners are normalized, bottom-left origin.
func quad(_ r: VNRectangleObservation, _ W: Double, _ H: Double) -> Quad {
    let tl = CGPoint(x: r.topLeft.x * W, y: r.topLeft.y * H), tr = CGPoint(x: r.topRight.x * W, y: r.topRight.y * H)
    let bl = CGPoint(x: r.bottomLeft.x * W, y: r.bottomLeft.y * H), br = CGPoint(x: r.bottomRight.x * W, y: r.bottomRight.y * H)
    let cx = Double(tl.x + tr.x + bl.x + br.x) / 4, cy = Double(tl.y + tr.y + bl.y + br.y) / 4
    let w = hypot(Double(tr.x - tl.x), Double(tr.y - tl.y)), h = hypot(Double(tl.x - bl.x), Double(tl.y - bl.y))
    return Quad(cx: cx, cy: cy, w: w, h: h, angle: atan2(Double(tr.y - tl.y), Double(tr.x - tl.x)))
}

func emit(_ obj: Any) {
    let data = (try? JSONSerialization.data(withJSONObject: obj)) ?? Data("{\"error\":\"encode\"}".utf8)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
}

struct Obs { var text: String; var conf: Float; var box: Quad; var words: [(String, Quad)]; var alt: String? = nil }

// One recognition pass over `roi` (normalized, bottom-left origin). Vision reports boxes
// relative to the ROI; they come back here in whole-image pixels.
func pass(_ cg: CGImage, _ roi: CGRect) throws -> [Obs] {
    let W = Double(cg.width), H = Double(cg.height)
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = false        // account numbers and amounts are not words
    req.recognitionLanguages = ["en-US", "es-ES"]
    req.regionOfInterest = roi
    try VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
    func q(_ r: VNRectangleObservation) -> Quad {
        var b = quad(r, Double(roi.width) * W, Double(roi.height) * H)
        b.cx += Double(roi.minX) * W; b.cy += Double(roi.minY) * H
        return b
    }
    var obs: [Obs] = []
    for o in req.results ?? [] {
        guard let c = o.topCandidates(1).first else { continue }
        let s = c.string
        guard let whole = try? c.boundingBox(for: s.startIndex..<s.endIndex) else { continue }
        var words: [(String, Quad)] = []
        var i = s.startIndex
        while i < s.endIndex {
            while i < s.endIndex && s[i] == " " { i = s.index(after: i) }
            if i >= s.endIndex { break }
            var e = i
            while e < s.endIndex && s[e] != " " { e = s.index(after: e) }
            if let b = try? c.boundingBox(for: i..<e) { words.append((String(s[i..<e]), q(b))) }
            i = e
        }
        obs.append(Obs(text: s, conf: c.confidence, box: q(whole), words: words))
    }
    return obs
}

// A reading that cannot be right: a character no statement prints (Vision sometimes ends an
// amount with "łął"), or a figure with a "$" that is not a well-formed amount ("$8/2.00").
let plain = CharacterSet(charactersIn: " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~áéíóúñüÁÉÍÓÚÑÜ¿¡°•·€£–—’‘“”…")
let money = try! NSRegularExpression(pattern: "^[-+(]?\\$-?(\\d{1,3}(,\\d{3})*|\\d+)\\.\\d{2}\\)?-?$")
let amountish = try! NSRegularExpression(pattern: "^[-+($]*\\d[\\d.,]*[.,]\\d{2}\\)?-?$")
let shortAmount = try! NSRegularExpression(pattern: "^[-+(]*(\\$\\d+|\\$?\\d{1,3}(,\\d{3})+)\\.\\d\\)?-?$")
let amount = try! NSRegularExpression(pattern: "^[-+(]?\\$?-?(\\d{1,3}(,\\d{3})*|\\d+)\\.\\d{2}\\)?-?$")
// the start of a figure, however its end was read ("220.9îŚ")
let figureStart = try! NSRegularExpression(pattern: "^[-+($]*\\d[\\d,]*\\.\\d")
let leadingDate = try! NSRegularExpression(pattern: "^(\\d{1,2}/\\d{1,2}|[A-Za-z]{3}\\.? \\d{1,2})\\b")
func matches(_ re: NSRegularExpression, _ w: String) -> Bool { re.firstMatch(in: w, range: NSRange(w.startIndex..., in: w)) != nil }
func hasAmount(_ s: String) -> Bool { s.split(separator: " ").contains { matches(amount, String($0)) } }
// A short figure Vision returns turned 180 degrees inside an upright box ("325.00" as "0O•SZE", "448.29" as
// "62'8+t", "220.99" as "66 022" -- First Community Bank's scanned check register, from a re-read of the
// row's strip): read back to front with each character turned over, it is a well-formed amount. It is
// not turned back here (an upside-down 7 came back "2": "332.67" as "29 ZEE"); it is read again.
let turnedOver: [Character: Character] = ["0": "0", "O": "0", "o": "0", "1": "1", "l": "1", "I": "1", "T": "1", "2": "2", "Z": "2", "z": "2",
                                          "E": "3", "h": "4", "t": "4", "+": "4", "S": "5", "s": "5", "9": "6", "L": "7", "8": "8", "6": "9"]
func readsTurned(_ s: String) -> Bool {
    if s.count < 4 || matches(amount, s) || !s.contains(where: { $0.isNumber }) { return false }
    var out: [Character] = []
    for c in s.reversed() {
        if let d = turnedOver[c] { out.append(d) } else if "'•·., ".contains(c) { out.append(",") } else { return false }
    }
    // the separator two digits from the end is the decimal point, any other a thousands comma
    if out.count < 4 || out[out.count - 3] != "," { return false }
    out[out.count - 3] = "."
    return matches(amount, String(out))
}
// a figure whose last cent is something else ("338.6s", "860.2€")
let garbledCents = try! NSRegularExpression(pattern: "^[-+($]*\\d[\\d,]*\\.\\d[^\\d\\s]+$")
func implausible(_ s: String) -> Bool {
    if s.unicodeScalars.contains(where: { !plain.contains($0) }) { return true }
    if readsTurned(s) { return true }
    for t in s.split(separator: " ") {
        let w = String(t)
        // "$8/2.00", a figure with its separators misread ("14.000.00"), or one cut short ("3,500.0")
        if w.contains("$") && !matches(money, w) { return true }
        if matches(amountish, w) && !matches(amount, w) { return true }
        if matches(shortAmount, w) { return true }
        if matches(garbledCents, w) { return true }
        // a date with a digit read as a slash ("0//31")
        if w.contains("//") && w.allSatisfy({ $0.isNumber || $0 == "/" }) { return true }
    }
    return false
}
func overlap(_ a: Quad, _ b: Quad) -> Double {   // intersection over the smaller box
    let ix = max(0, min(a.cx + a.w / 2, b.cx + b.w / 2) - max(a.cx - a.w / 2, b.cx - b.w / 2))
    let iy = max(0, min(a.cy + a.h / 2, b.cy + b.h / 2) - max(a.cy - a.h / 2, b.cy - b.h / 2))
    return ix * iy / max(1, min(a.w * a.h, b.w * b.h))
}

// Re-read one region of the page (pixels, top-left origin) at twice the size.
func reread(_ cg: CGImage, _ rect: CGRect, margin: Int = 0, scale: Double = 2) -> [Obs] {
    let H = Double(cg.height)
    let r = rect.intersection(CGRect(x: 0, y: 0, width: cg.width, height: cg.height)).integral
    guard r.width > 8, r.height > 8, let crop = cg.cropping(to: r) else { return [] }
    // The strip sits in the middle of a white canvas at least a fifth as tall as it is wide:
    // given a bare 30:1 strip, Vision read "05/13 ... 1,000.00" upside down, as "81/90" and "00:0001".
    let k = scale, w = Int(Double(r.width) * k), h = Int(Double(r.height) * k)
    let cw = w + 2 * margin, ch = max(h + 2 * margin, cw / 5), ox = margin, oy = (ch - h) / 2
    guard let ctx = CGContext(data: nil, width: cw, height: ch, bitsPerComponent: 8, bytesPerRow: 0,
                              space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return [] }
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1)); ctx.fill(CGRect(x: 0, y: 0, width: cw, height: ch))
    ctx.interpolationQuality = .high
    ctx.draw(crop, in: CGRect(x: ox, y: oy, width: w, height: h))
    guard let up = ctx.makeImage(), let found = try? pass(up, CGRect(x: 0, y: 0, width: 1, height: 1)) else { return [] }
    func back(_ q: Quad) -> Quad {   // canvas pixels (bottom-left) -> page pixels (bottom-left)
        Quad(cx: Double(r.minX) + (q.cx - Double(ox)) / k, cy: (H - Double(r.maxY)) + (q.cy - Double(oy)) / k, w: q.w / k, h: q.h / k, angle: q.angle)
    }
    return found.map { o in Obs(text: o.text, conf: o.conf, box: back(o.box), words: o.words.map { ($0.0, back($0.1)) }) }
}

// The page turned by a quarter turns (1 = 90° clockwise).
func rotated(_ cg: CGImage, _ quarters: Int) -> CGImage? {
    let w = cg.width, h = cg.height, odd = quarters % 2 == 1
    guard let ctx = CGContext(data: nil, width: odd ? h : w, height: odd ? w : h, bitsPerComponent: 8, bytesPerRow: 0,
                              space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return nil }
    let cw = Double(odd ? h : w), chh = Double(odd ? w : h)
    ctx.translateBy(x: cw / 2, y: chh / 2)
    ctx.rotate(by: -Double(quarters) * .pi / 2)
    ctx.draw(cg, in: CGRect(x: -Double(w) / 2, y: -Double(h) / 2, width: Double(w), height: Double(h)))
    return ctx.makeImage()
}

// A PDF page drawn by PDFKit at the size the extractor's own renderer uses (long edge
// 2200 px, at most 3x): about 200 dpi for Letter. PDFKit draws a scan's embedded image with
// proper smoothing; pdf.js in the browser drew Chase's compressed scans coarser, and Vision
// dropped rows from those renders that it read from these.
func pdfPage(_ path: String, _ index: Int) -> Any {
    guard let doc = PDFDocument(url: URL(fileURLWithPath: path)), let page = doc.page(at: index) else { return ["error": "could not open page \(index + 1) of the PDF"] }
    let box = page.bounds(for: .mediaBox), turned = page.rotation % 180 != 0
    let wPt = Double(turned ? box.height : box.width), hPt = Double(turned ? box.width : box.height)
    let scale = min(3.0, 2200.0 / max(wPt, hPt, 1))
    let img = page.thumbnail(of: NSSize(width: wPt * scale, height: hPt * scale), for: .mediaBox)
    guard let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return ["error": "could not draw page \(index + 1)"] }
    guard var out = recognize(cg) as? [String: Any] else { return ["error": "recognition failed"] }
    out["pxPerPt"] = Double(cg.width) / wPt; out["heightPt"] = hPt
    return out
}

func recognize(_ path: String) -> Any {
    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return ["error": "could not decode the page image"] }
    return recognize(cg)
}

func recognize(_ image: CGImage) -> Any {
    let t0 = Date()
    var cg = image
    // A page scanned sideways or upside down: Vision still reads its lines, at 90° or 180°, and
    // the margin rule below would throw them all away (an AIA G702 fed in turned: no text
    // left). When most of a page's text runs one other way, the page is turned to match and
    // read again; the turn is kept only if the text then reads upright. A page that reads
    // upright costs nothing extra -- this first pass doubles as the orientation check.
    var turned = 0, upright: [Obs]? = nil
    if let up = try? pass(cg, CGRect(x: 0, y: 0, width: 1, height: 1)) {
        upright = up
        func way(_ a: Double) -> Int { Int(((a * 180 / .pi) + 405).truncatingRemainder(dividingBy: 360) / 90) }  // 0 up, 1 = text rising (90°), 2 = 180°, 3 = 270°
        func uprightShare(_ o: [Obs]) -> Double {
            let total = o.map { Double($0.text.count) }.reduce(0, +)
            return total == 0 ? 0 : o.filter { way($0.box.angle) == 0 }.map { Double($0.text.count) }.reduce(0, +) / total
        }
        var share = [0.0, 0.0, 0.0, 0.0]
        for o in up { share[way(o.box.angle)] += Double(o.text.count) }
        let total = share.reduce(0, +)
        if total > 0, let dom = (1...3).max(by: { share[$0] < share[$1] }), share[dom] / total > 0.6 {
            // text rising at 90° is righted by a quarter turn clockwise; the other ways follow
            for q in (dom == 2 ? [2] : [dom, 4 - dom]) {
                if let r = rotated(cg, q), let again = try? pass(r, CGRect(x: 0, y: 0, width: 1, height: 1)), uprightShare(again) > 0.6 {
                    cg = r; turned = q; upright = again; break
                }
            }
        }
    }
    let W = Double(cg.width), H = Double(cg.height)
    // Two readings of the page. Vision finds text on a reduced copy of the image, so on a
    // dense statement page it skips some short isolated words (whole dates: "Aug 19" gone
    // while its row's description and amount were read). Three overlapping bands, each
    // keeping the lines centred in its own third, recover them (12-page ConnectOne scan:
    // every date, against 17 of 21 on one page read whole). The whole-page reading is the
    // second opinion: where one reading garbles a line the other usually has it clean.
    var obs: [Obs] = [], whole: [Obs] = []
    do {
        let pad = 0.03
        for k in 0..<3 {
            let lo = Double(k) / 3, hi = Double(k + 1) / 3          // top-down fractions
            let a0 = max(0, lo - pad), a1 = min(1, hi + pad)
            for o in try pass(cg, CGRect(x: 0, y: 1 - a1, width: 1, height: a1 - a0)) {
                let c = 1 - o.box.cy / H
                if c >= lo && c < hi { obs.append(o) }
            }
        }
        whole = try upright ?? pass(cg, CGRect(x: 0, y: 0, width: 1, height: 1))
    } catch { return ["error": "\(error)"] }
    // Skew: median slope of the long lines (short ones are too noisy to measure).
    let tilt = 10.0 * .pi / 180
    let slopes = obs.filter { $0.box.w > W * 0.15 && abs($0.box.angle) < tilt }.map { $0.box.angle }.sorted()
    let skew = slopes.isEmpty ? 0 : slopes[slopes.count / 2]
    // Text running another way (the sideways mail-sort code down a statement's margin) is
    // left out, before anything is matched by position: its box lies across the rows it
    // passes, and placed by its centre it would land in one of them.
    // The page's level: a box's height with the skew turned out, as place() reports it. Rows are
    // grouped on it -- on a scan 2° crooked a row's amount sits ~60 px off its date's height.
    let cosA = cos(-skew), sinA = sin(-skew), ox = W / 2, oy = H / 2
    func level(_ q: Quad) -> Double { oy + (q.cx - ox) * sinA + (q.cy - oy) * cosA }
    let sideways = obs.filter { abs($0.box.angle - skew) > 2 * tilt }.count
    obs = obs.filter { abs($0.box.angle - skew) <= 2 * tilt }
    whole = whole.filter { abs($0.box.angle - skew) <= 2 * tilt }
    var replaced = 0, added = 0
    for i in obs.indices {
        guard let m = whole.first(where: { overlap($0.box, obs[i].box) > 0.6 && abs($0.box.w - obs[i].box.w) < obs[i].box.h * 2 }),
              m.text != obs[i].text, !implausible(m.text) else { continue }
        // a garbled reading gives way to the clean one; two clean readings that disagree
        // ("Aug 21" / "Aug 27") are both passed on, for the extractor to settle from context
        if implausible(obs[i].text) { obs[i] = m; replaced += 1 } else { obs[i].alt = m.text }
    }
    for o in whole where !obs.contains(where: { overlap($0.box, o.box) > 0.2 }) { obs.append(o); added += 1 }

    // Rows still wrong after both readings -- a figure still garbled, or a dated row with no
    // amount at all (Vision dropped "520.45" from one of fifteen identical card rows) -- are read
    // again on their own, from a strip of the page at twice the size.
    let medH = obs.map { $0.box.h }.sorted().dropFirst(obs.count / 2).first ?? 30
    let byY = obs.indices.sorted { level(obs[$0].box) > level(obs[$1].box) }   // top of the page first
    var rowsOf: [[Int]] = []
    for i in byY {
        if let last = rowsOf.last?.first, abs(level(obs[last].box) - level(obs[i].box)) < medH * 0.5 { rowsOf[rowsOf.count - 1].append(i) }
        else { rowsOf.append([i]) }
    }
    let datedWithAmount = rowsOf.filter { r in
        let first = r.min { obs[$0].box.cx - obs[$0].box.w / 2 < obs[$1].box.cx - obs[$1].box.w / 2 }!
        return matches(leadingDate, obs[first].text) && r.contains { hasAmount(obs[$0].text) }
    }.count
    var reread_ = 0
    for r in rowsOf {
        let first = r.min { obs[$0].box.cx - obs[$0].box.w / 2 < obs[$1].box.cx - obs[$1].box.w / 2 }!
        let bad = r.contains { implausible(obs[$0].text) }
        let noAmount = datedWithAmount >= 3 && matches(leadingDate, obs[first].text) && !r.contains { hasAmount(obs[$0].text) }
        if !bad && !noAmount { continue }
        let top = r.map { H - (obs[$0].box.cy + obs[$0].box.h / 2) }.min()!, bottom = r.map { H - (obs[$0].box.cy - obs[$0].box.h / 2) }.max()!
        let strip = reread(cg, CGRect(x: 0, y: top - medH * 0.45, width: W, height: bottom - top + medH * 0.9))
        reread_ += 1
        for n in strip where !implausible(n.text) {
            // the same text block: a clean reading replaces a garbled one -- a figure only by a figure
            // ("341.0ł" came back from its row's strip as "TOIDE")
            if let j = r.first(where: { overlap(obs[$0].box, n.box) > 0.5 && abs(obs[$0].box.w - n.box.w) < n.box.h * 2 }), implausible(obs[j].text) {
                if matches(figureStart, obs[j].text) && !hasAmount(n.text) { continue }
                obs[j] = n; replaced += 1; continue
            }
            // a figure or date the page readings missed (only those are taken from a strip)
            for w in n.words where (matches(amount, w.0) || matches(leadingDate, w.0)) && !obs.contains(where: { overlap($0.box, w.1) > 0.3 }) {
                obs.append(Obs(text: w.0, conf: n.conf, box: w.1, words: [w])); added += 1
            }
        }
    }

    // A reading still garbled after that -- or, on a dated row with no amount, a bare number where
    // the amount sits ("$6,764.89" read "68929") -- is read once more alone, from a crop of its
    // own box at a few sizes. The crop is tight: a table rule touching a figure is what Vision
    // reads as "łął" ("$519.80|" -> "$519.8ąłą"), so a garbled tail is cut off, and the rows
    // above and below are left out. (Chase's "07/31" came back "0//31" from the page and its
    // row strip; tight crops of First Security's two cells read right at every size.)
    func rowOf(_ i: Int) -> [Int] { obs.indices.filter { abs(level(obs[$0].box) - level(obs[i].box)) < medH * 0.5 } }
    func datedNoAmount(_ i: Int) -> Bool {
        let row = rowOf(i)
        guard let first = row.min(by: { obs[$0].box.cx - obs[$0].box.w / 2 < obs[$1].box.cx - obs[$1].box.w / 2 }) else { return false }
        return datedWithAmount >= 3 && matches(leadingDate, obs[first].text) && !row.contains { hasAmount(obs[$0].text) }
    }
    let numberish = try! NSRegularExpression(pattern: "^[-+($]*\\d[\\d.,]{2,}\\)?-?$")
    for i in obs.indices {
        let t = obs[i].text, bare = !hasAmount(t) && matches(numberish, t) && datedNoAmount(i)
        guard implausible(t) || bare else { continue }
        let b = obs[i].box
        // keep the readable start of a garbled reading and a character or two more (the width is
        // estimated from character counts, so two cuts are tried) -- after the whole box: Vision can
        // give one real digit as three garbled characters ("220.9îŚ" for "220.99"), and a cut that
        // ends inside that digit reads it as another ("220.95")
        let clean = t.unicodeScalars.prefix { plain.contains($0) }.count
        let widths = clean < t.count ? [b.w] + [1.0, 2.0].map { b.w * Double(min(t.count, clean + Int($0))) / Double(max(t.count, 1)) } : [b.w]
        // a figure must come back whole ("325.0îęŚ" read again in a narrow crop is "325.0")
        let figure = matches(figureStart, t)
        var done = false
        for w in widths where !done { for k in [2.0, 3.0, 1.0] where !done {
            let rect = CGRect(x: b.cx - b.w / 2 - b.h * 0.15, y: H - b.cy - b.h * 0.6, width: w + b.h * 0.3, height: b.h * 1.2)
            let cell = reread(cg, rect, margin: Int(b.h * 2), scale: k)
            let text = cell.filter { !implausible($0.text) }.sorted { $0.box.cx < $1.box.cx }.map { $0.text }.joined(separator: " ")
            if text.isEmpty || implausible(text) || (!bare && abs(Double(text.count - clean)) > 3) { continue }
            if bare && !hasAmount(text) { continue }
            // (exactly a figure: the whole box can take in a table rule beside it, "$519.80 |")
            if figure && !matches(amount, text) { continue }
            obs[i].text = text; obs[i].words = [(text, b)]; replaced += 1
            done = true
        } }
    }

    func place(_ q: Quad) -> [String: Double] {
        let dx = q.cx - ox, dy = q.cy - oy
        let x = ox + dx * cosA - dy * sinA, y = oy + dx * sinA + dy * cosA   // still bottom-left origin
        return ["x": x - q.w / 2, "y": (H - y) - q.h / 2, "w": q.w, "h": q.h]
    }
    let lines: [[String: Any]] = obs.map { o in
        var d: [String: Any] = place(o.box)
        d["t"] = o.text; d["c"] = Double(o.conf)
        if let a = o.alt { d["a"] = a }
        d["words"] = o.words.map { w -> [String: Any] in var wd: [String: Any] = place(w.1); wd["t"] = w.0; return wd }
        return d
    }
    return ["w": W, "h": H, "secs": Date().timeIntervalSince(t0), "skew": skew * 180 / .pi, "sideways": sideways,
            "turned": turned * 90, "replaced": replaced, "added": added, "reread": reread_, "implausible": obs.filter { implausible($0.text) }.count, "lines": lines]
}

while let line = readLine() {
    let req = line.trimmingCharacters(in: .newlines)
    if req.trimmingCharacters(in: .whitespaces).isEmpty { continue }
    let f = req.components(separatedBy: "\t")
    autoreleasepool {
        if f[0] == "pdf" && f.count == 3, let n = Int(f[2]) { emit(pdfPage(f[1], n)) }
        else if f[0] == "count" && f.count == 2 { emit(["pages": PDFDocument(url: URL(fileURLWithPath: f[1]))?.pageCount ?? 0]) }
        else { emit(recognize(req)) }
    }
}
