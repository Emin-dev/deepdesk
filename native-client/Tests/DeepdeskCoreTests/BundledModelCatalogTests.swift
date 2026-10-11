import Foundation
import XCTest
import Darwin
@testable import DeepdeskCore

final class BundledModelCatalogTests: XCTestCase {
    private func temporaryRoot() throws -> URL {
        let root = FileManager.default.temporaryDirectory.resolvingSymlinksInPath()
            .appendingPathComponent("DeepdeskResources-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try FileManager.default.removeItem(at: root) }
        return root
    }

    private func makeApp(in root: URL, standardBundleLayout: Bool = false) throws -> (app: URL, bundle: URL, catalog: URL) {
        let app = root.appendingPathComponent("Deepdesk.app", isDirectory: true)
        let bundle = app.appendingPathComponent("Contents/Resources/Deepdesk_Deepdesk.bundle", isDirectory: true)
        let resources = standardBundleLayout ? bundle.appendingPathComponent("Contents/Resources", isDirectory: true) : bundle
        try FileManager.default.createDirectory(at: resources, withIntermediateDirectories: true)
        let info = standardBundleLayout ? bundle.appendingPathComponent("Contents/Info.plist") : bundle.appendingPathComponent("Info.plist")
        let plist: [String: String] = ["CFBundleIdentifier": "dev.emin.deepdesk.resource-fixture.\(UUID().uuidString)",
                                     "CFBundlePackageType": "BNDL"]
        try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0).write(to: info)
        let catalog = resources.appendingPathComponent("model-catalog.json")
        let fixture = try XCTUnwrap(Bundle.module.url(forResource: "model-catalog", withExtension: "json"))
        try FileManager.default.copyItem(at: fixture, to: catalog)
        return (app, bundle, catalog)
    }

    func testFlatPackagedCatalogLoadsBothCuratedModels() throws {
        let fixture = try makeApp(in: temporaryRoot())
        let catalog = try BundledModelCatalog.load(applicationBundleURL: fixture.app)
        XCTAssertEqual(catalog.models.map(\.id), ["qwen38-27b-splash", "qwen38-27b-uncensored"])
    }

    func testStandardMacBundleResourceLayoutLoads() throws {
        let fixture = try makeApp(in: temporaryRoot(), standardBundleLayout: true)
        XCTAssertEqual(try BundledModelCatalog.load(applicationBundleURL: fixture.app).models.count, 2)
    }

    func testRelocatedAppLoadsAfterOriginalPathDisappears() throws {
        let root = try temporaryRoot()
        let fixture = try makeApp(in: root)
        let moved = root.appendingPathComponent("Relocated.app", isDirectory: true)
        try FileManager.default.moveItem(at: fixture.app, to: moved)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.app.path))
        XCTAssertEqual(try BundledModelCatalog.load(applicationBundleURL: moved).models.count, 2)
    }

    func testBundleAtAppRootIsNotAcceptedAsFallback() throws {
        let fixture = try makeApp(in: temporaryRoot())
        try FileManager.default.moveItem(at: fixture.bundle,
                                        to: fixture.app.appendingPathComponent(BundledModelCatalog.resourceBundleName))
        XCTAssertThrowsError(try BundledModelCatalog.load(applicationBundleURL: fixture.app))
    }

    func testAdjacentBuildStyleBundleCannotReplaceMissingPackagedBundle() throws {
        let root = try temporaryRoot()
        let fixture = try makeApp(in: root)
        try FileManager.default.moveItem(at: fixture.bundle,
                                        to: root.appendingPathComponent(BundledModelCatalog.resourceBundleName))
        XCTAssertThrowsError(try BundledModelCatalog.load(applicationBundleURL: fixture.app))
        XCTAssertThrowsError(try BundledModelCatalog.load(applicationBundleURL: root))
    }

    func testResourceBundleSymlinkIsRejected() throws {
        let root = try temporaryRoot()
        let fixture = try makeApp(in: root)
        let outside = root.appendingPathComponent("Elsewhere.bundle")
        try FileManager.default.moveItem(at: fixture.bundle, to: outside)
        try FileManager.default.createSymbolicLink(at: fixture.bundle, withDestinationURL: outside)
        XCTAssertThrowsError(try BundledModelCatalog.load(applicationBundleURL: fixture.app))
    }

    func testAppSymlinkIsRejected() throws {
        let root = try temporaryRoot()
        let fixture = try makeApp(in: root)
        let linked = root.appendingPathComponent("Linked.app")
        try FileManager.default.createSymbolicLink(at: linked, withDestinationURL: fixture.app)
        XCTAssertThrowsError(try BundledModelCatalog.load(applicationBundleURL: linked))
    }

    func testAncestorSymlinkIsRejected() throws {
        let root = try temporaryRoot()
        let nested = root.appendingPathComponent("real", isDirectory: true)
        _ = try makeApp(in: nested)
        let linked = root.appendingPathComponent("linked", isDirectory: true)
        try FileManager.default.createSymbolicLink(at: linked, withDestinationURL: nested)
        XCTAssertThrowsError(try BundledModelCatalog.load(applicationBundleURL: linked.appendingPathComponent("Deepdesk.app")))
    }

    func testNestedResourcesDirectorySymlinkIsRejected() throws {
        let root = try temporaryRoot()
        let fixture = try makeApp(in: root, standardBundleLayout: true)
        let resources = fixture.catalog.deletingLastPathComponent()
        let outside = root.appendingPathComponent("outside", isDirectory: true)
        try FileManager.default.moveItem(at: resources, to: outside)
        try FileManager.default.createSymbolicLink(at: resources, withDestinationURL: outside)
        XCTAssertThrowsError(try BundledModelCatalog.load(applicationBundleURL: fixture.app))
    }

    func testCatalogSymlinkIsRejected() throws {
        let root = try temporaryRoot()
        let fixture = try makeApp(in: root)
        let outside = root.appendingPathComponent("elsewhere.json")
        try FileManager.default.moveItem(at: fixture.catalog, to: outside)
        try FileManager.default.createSymbolicLink(at: fixture.catalog, withDestinationURL: outside)
        XCTAssertThrowsError(try BundledModelCatalog.load(applicationBundleURL: fixture.app))
    }

    func testCatalogHardlinkIsRejected() throws {
        let root = try temporaryRoot()
        let fixture = try makeApp(in: root)
        try FileManager.default.linkItem(at: fixture.catalog, to: root.appendingPathComponent("hardlink.json"))
        XCTAssertThrowsError(try BundledModelCatalog.load(applicationBundleURL: fixture.app))
    }

    func testCatalogFIFOIsRejectedWithoutBlocking() throws {
        let fixture = try makeApp(in: temporaryRoot())
        try FileManager.default.removeItem(at: fixture.catalog)
        XCTAssertEqual(mkfifo(fixture.catalog.path, 0o600), 0)
        XCTAssertThrowsError(try BundledModelCatalog.load(applicationBundleURL: fixture.app))
    }

    func testMissingCatalogFailsClosed() throws {
        let fixture = try makeApp(in: temporaryRoot())
        try FileManager.default.removeItem(at: fixture.catalog)
        XCTAssertThrowsError(try BundledModelCatalog.load(applicationBundleURL: fixture.app))
    }

    func testOversizedCatalogIsRejectedBeforeDecoding() throws {
        let fixture = try makeApp(in: temporaryRoot())
        try Data(repeating: 32, count: BundledModelCatalog.maximumBytes + 1).write(to: fixture.catalog)
        XCTAssertThrowsError(try BundledModelCatalog.load(applicationBundleURL: fixture.app))
    }

    func testInvalidAndEmptyCatalogsFailClosed() throws {
        let fixture = try makeApp(in: temporaryRoot())
        try Data("invalid JSON".utf8).write(to: fixture.catalog)
        XCTAssertThrowsError(try BundledModelCatalog.load(applicationBundleURL: fixture.app))
        try Data("{\"version\":2,\"models\":[]}".utf8).write(to: fixture.catalog)
        XCTAssertThrowsError(try BundledModelCatalog.load(applicationBundleURL: fixture.app))
        try Data("{\"version\":1,\"models\":[]}".utf8).write(to: fixture.catalog)
        XCTAssertThrowsError(try BundledModelCatalog.load(applicationBundleURL: fixture.app))
    }
}
