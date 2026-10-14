// SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
// SPDX-License-Identifier: GPL-2.0-or-later
//
// Poll the on-screen windows of one process every 10 ms; print a line whenever the set changes.
import Foundation
import CoreGraphics
let pid = Int32(CommandLine.arguments[1])!
let seconds = Double(CommandLine.arguments[2]) ?? 6
let start = Date()
var last = ""
while Date().timeIntervalSince(start) < seconds {
    let list = (CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as? [[String: Any]]) ?? []
    var rows: [String] = []
    for w in list where (w[kCGWindowOwnerPID as String] as? Int32) == pid {
        let b = w[kCGWindowBounds as String] as? [String: Double] ?? [:]
        let num = w[kCGWindowNumber as String] as? Int ?? 0
        let layer = w[kCGWindowLayer as String] as? Int ?? 0
        let alpha = w[kCGWindowAlpha as String] as? Double ?? 1
        rows.append("#\(num) L\(layer) a\(String(format: "%.2f", alpha)) \(Int(b["Width"] ?? 0))x\(Int(b["Height"] ?? 0))@\(Int(b["X"] ?? 0)),\(Int(b["Y"] ?? 0))")
    }
    let cur = rows.joined(separator: " > ")
    if cur != last {
        print(String(format: "%7.3f ", Date().timeIntervalSince(start)) + cur)
        fflush(stdout)
        last = cur
    }
    usleep(10000)
}
