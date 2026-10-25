import SwiftUI

// 显式使用属性包装器，以兼容没有 SwiftUI 宏插件的命令行工具链。
typealias GroveState<Value> = SwiftUI.State<Value>

extension Color {
    init(hex: String) {
        let value = UInt64(hex.replacingOccurrences(of: "#", with: ""), radix: 16) ?? 0
        self.init(.sRGB, red: Double((value >> 16) & 255) / 255, green: Double((value >> 8) & 255) / 255, blue: Double(value & 255) / 255, opacity: 1)
    }
}


import SwiftUI
import AppKit

struct GrovePalette {
    var dark: Bool = false
    var background: Color { Color(hex: dark ? "101A17" : "F5F6F1") }
    var sidebar: Color { Color(hex: dark ? "15201C" : "ECEFE7") }
    var card: Color { Color(hex: dark ? "1B2822" : "FFFFFF") }
    var text: Color { Color(hex: dark ? "E7EEE5" : "253B30") }
    var secondary: Color { Color(hex: dark ? "A0B3A5" : "768276") }
    var line: Color { Color(hex: dark ? "304138" : "E9EDE5") }
    var accent: Color { Color(hex: dark ? "B9DA8C" : "487341") }
    var soft: Color { Color(hex: dark ? "273D2B" : "E8F0DE") }
    var hero: Color { Color(hex: dark ? "25372B" : "EAF0E1") }
    var levels: [Color] { (dark ? ["293A30", "405C3B", "648A48", "94BC65", "C7E795"] : ["EDF0E8", "D1E3B6", "A2C67C", "719D50", "456D3D"]).map { Color(hex: $0) } }
}

struct GroveMark: View {
    var size: CGFloat = 36
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.29).fill(Color(hex: "2C4938"))
            Image(systemName: "leaf.fill").font(.system(size: size * 0.50, weight: .medium)).rotationEffect(.degrees(-18)).foregroundStyle(Color(hex: "CEE6A9"))
        }.frame(width: size, height: size)
    }
}

struct CapsuleLabel: View {
    var text: String
    var icon: String? = nil
    var palette = GrovePalette()
    var body: some View {
        HStack(spacing: 5) {
            if let icon { Image(systemName: icon).font(.system(size: 10, weight: .semibold)) }
            Text(text).font(.system(size: 11, weight: .medium))
        }.foregroundStyle(palette.accent).padding(.horizontal, 10).padding(.vertical, 6).background(palette.soft, in: Capsule())
    }
}


import SwiftUI
import AppKit
import Charts

struct SectionHeading: View {
    var eyebrow:String;var title:String;var subtitle:String
    var body:some View {VStack(alignment:.leading,spacing:8){Text(eyebrow).font(.system(size:9,weight:.semibold)).tracking(2).opacity(0.55);Text(title).font(.system(size:28,weight:.medium));Text(subtitle).font(.system(size:12)).opacity(0.6)}}
}
struct GroveTile: View {
    var title:String;var value:String;var detail:String;var icon:String;var p:GrovePalette
    var body:some View {
        VStack(alignment:.leading,spacing:15){HStack{Text(title).font(.system(size:11));Spacer();Image(systemName:icon).foregroundStyle(p.accent)};Text(value).font(.system(size:25,weight:.light,design:.rounded)).monospacedDigit().lineLimit(1).minimumScaleFactor(0.7);Text(detail).font(.system(size:10)).foregroundStyle(p.secondary).lineLimit(2)}.padding(20).frame(maxWidth:.infinity,alignment:.leading).frame(height:140).background(p.card,in:RoundedRectangle(cornerRadius:18))
    }
}

enum GroveError: LocalizedError { case message(String); var errorDescription: String? { if case let .message(s) = self { return s }; return nil } }
