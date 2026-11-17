import Foundation

enum InterfaceLanguage: String, CaseIterable {
    case chinese = "zh-CN"
    case japanese = "ja"
    case english = "en"

    private static let storageKey = "interfaceLanguage"

    static var current: Self {
        UserDefaults.standard.string(forKey: storageKey).flatMap(Self.init(rawValue:)) ?? .chinese
    }

    func save() {
        UserDefaults.standard.set(rawValue, forKey: Self.storageKey)
    }

    var label: String {
        switch self {
        case .chinese: return "简体中文"
        case .japanese: return "日本語"
        case .english: return "English"
        }
    }
}

private let substitution = try! NSRegularExpression(pattern: #"\{([0-9]+)\}"#)

func localized(_ source: String, _ values: Any...) -> String {
    let translations: [String: String]
    switch InterfaceLanguage.current {
    case .chinese: translations = [:]
    case .japanese: translations = japaneseMessages
    case .english: translations = englishMessages
    }
    let template = translations[source] ?? source
    guard !values.isEmpty else { return template }
    let output = NSMutableString(string: template)
    for match in substitution.matches(in: template, range: NSRange(template.startIndex..., in: template)).reversed() {
        if let range = Range(match.range(at: 1), in: template),
           let index = Int(template[range]), values.indices.contains(index) {
            output.replaceCharacters(in: match.range, with: String(describing: values[index]))
        }
    }
    return output as String
}
