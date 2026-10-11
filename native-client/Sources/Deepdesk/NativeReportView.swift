#if os(macOS)
import SwiftUI
import DeepdeskCore

/// Native text blocks only. No HTML, WebView, JavaScript, image fetch, or automatic URL opening.
struct NativeReportView: View {
    let content: String

    var body: some View {
        LazyVStack(alignment: .leading, spacing: 16) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                switch block {
                case .heading(let text, let level):
                    Text(verbatim: text)
                        .font(level == 1 ? .title2.bold() : .headline)
                        .accessibilityAddTraits(.isHeader)
                        .padding(.top, level == 1 ? 12 : 4)
                case .paragraph(let text):
                    Text(verbatim: text).font(.body).lineSpacing(5)
                case .code(let text):
                    Text(verbatim: text)
                        .font(.system(.callout, design: .monospaced))
                        .padding(14)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 10))
                }
            }
        }
        .textSelection(.enabled)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private enum Block { case heading(String, Int), paragraph(String), code(String) }

    private var blocks: [Block] {
        var result: [Block] = []
        var paragraph: [String] = []
        var code: [String] = []
        var inCode = false
        func flushParagraph() {
            if !paragraph.isEmpty {
                result.append(.paragraph(paragraph.joined(separator: "\n")))
                paragraph = []
            }
        }
        for line in content.components(separatedBy: .newlines) {
            if line.hasPrefix("```") {
                flushParagraph()
                if inCode { result.append(.code(code.joined(separator: "\n"))); code = [] }
                inCode.toggle()
            } else if inCode { code.append(line) }
            else if line.trimmingCharacters(in: .whitespaces).isEmpty { flushParagraph() }
            else if line.hasPrefix("#") {
                let level = line.prefix(while: { $0 == "#" }).count
                if level <= 6 && line.dropFirst(level).hasPrefix(" ") {
                    flushParagraph()
                    result.append(.heading(String(line.dropFirst(level + 1)), level))
                } else { paragraph.append(line) }
            } else { paragraph.append(line) }
        }
        flushParagraph()
        if !code.isEmpty { result.append(.code(code.joined(separator: "\n"))) }
        return result
    }
}

struct SourcesView: View {
    let sources: [ResearchSource]
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Sources").font(.title3.bold()).accessibilityAddTraits(.isHeader)
            Text("Source order is supplied by the engine and may differ from numbered citations in the report.")
                .font(.caption).foregroundStyle(.secondary)
            if sources.isEmpty {
                Text("No source links were returned for this report.").foregroundStyle(.secondary)
            }
            ForEach(sources) { source in
                VStack(alignment: .leading, spacing: 4) {
                    if let url = source.safeURL {
                        Link(destination: url) {
                            Label(source.displayTitle, systemImage: "arrow.up.right")
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .accessibilityHint("Opens this source in your default browser.")
                        Text(url.host ?? "").font(.caption).foregroundStyle(.secondary)
                    } else {
                        Text(source.displayTitle)
                        Text("Link unavailable: unsupported URL.").font(.caption).foregroundStyle(.secondary)
                    }
                }
                Divider()
            }
        }
        .textSelection(.enabled)
        .padding(22)
    }
}

struct GlassControlSurface: ViewModifier {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    func body(content: Content) -> some View {
        if reduceTransparency {
            content.background(Color(nsColor: .controlBackgroundColor), in: Capsule())
        } else {
            #if compiler(>=6.2)
            if #available(macOS 26.0, *) {
                content.glassEffect(.regular, in: Capsule())
            } else {
                content.background(.regularMaterial, in: Capsule())
            }
            #else
            content.background(.regularMaterial, in: Capsule())
            #endif
        }
    }
}
#endif
