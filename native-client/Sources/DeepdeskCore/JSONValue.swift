import Foundation

/// Used only for fields whose upstream shape is intentionally variable.
public enum JSONValue: Codable, Equatable, Sendable {
    case string(String), number(Double), bool(Bool), object([String: JSONValue]), array([JSONValue]), null

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let value = try? c.decode(Bool.self) { self = .bool(value) }
        else if let value = try? c.decode(String.self) { self = .string(value) }
        else if let value = try? c.decode(Double.self) { self = .number(value) }
        else if let value = try? c.decode([String: JSONValue].self) { self = .object(value) }
        else { self = .array(try c.decode([JSONValue].self)) }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let value): try c.encode(value)
        case .number(let value): try c.encode(value)
        case .bool(let value): try c.encode(value)
        case .object(let value): try c.encode(value)
        case .array(let value): try c.encode(value)
        case .null: try c.encodeNil()
        }
    }

    public var string: String? {
        if case .string(let value) = self { return value }
        return nil
    }
    public var number: Double? {
        if case .number(let value) = self { return value }
        return nil
    }
    public var object: [String: JSONValue]? {
        if case .object(let value) = self { return value }
        return nil
    }
    public var array: [JSONValue]? {
        if case .array(let value) = self { return value }
        return nil
    }
    public subscript(_ key: String) -> JSONValue? { object?[key] }
}
