import XCTest
import AppKit

final class DeepdeskUITests: XCTestCase {
    @MainActor private var app: XCUIApplication!

    @MainActor private func launch(arguments: [String] = []) {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = arguments
        app.launch()
    }
    @MainActor private func element(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }
    @MainActor private func visibleText(_ element: XCUIElement) -> String {
        // AppKit static text commonly exposes AXValue rather than AXLabel.
        if let value = element.value as? String, !value.isEmpty { return value }
        return element.label
    }
    @MainActor private func expectText(_ identifier: String, equals expected: String, timeout: TimeInterval) {
        let target = element(identifier)
        let predicate = NSPredicate(format: "label == %@ OR value == %@", expected, expected)
        let result = XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: predicate, object: target)], timeout: timeout)
        if target.exists {
            print("DEEPDESK_SYNTHETIC_AX id=\(identifier) label=\(target.label.prefix(150)) value=\(String(describing: target.value).prefix(200))")
        }
        XCTAssertEqual(result, .completed, "Expected exact visible text: \(expected)")
    }
    @MainActor private func screenshot(_ name: String) {
        XCTAssertTrue(element("synthetic-host-banner").exists)
        let sheetNotice = element("model.presentation-notice")
        let notice = sheetNotice.exists ? sheetNotice : element("synthetic-host-banner")
        XCTAssertTrue(notice.isHittable)
        notice.hover()
        // Let the runner Dock/tooltip retract after earlier pointer actions; no OS setting changes.
        Thread.sleep(forTimeInterval: 1.0)
        let attachment = XCTAttachment(screenshot: app.windows.firstMatch.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
    @MainActor private func setUpResearch() {
        XCTAssertTrue(element("synthetic-host-banner").waitForExistence(timeout: 10))
        let consent = element("onboarding.consent")
        XCTAssertTrue(consent.waitForExistence(timeout: 5))
        XCTAssertFalse(element("onboarding.continue").isEnabled)
        consent.click()
        element("onboarding.continue").click()
        XCTAssertTrue(element("research.question").waitForExistence(timeout: 8))
        XCTAssertFalse(element("research.start").isEnabled)
    }
    @MainActor private func chooseSplashModel() {
        app.buttons["Choose a model"].click()
        let download = element("model.download.qwen38-27b-splash")
        XCTAssertTrue(download.waitForExistence(timeout: 5))
        XCTAssertTrue(element("model.selected.qwen38-27b-splash").exists)
        download.click()
        let pause = element("model.pause.qwen38-27b-splash")
        XCTAssertTrue(pause.waitForExistence(timeout: 3))
        let progress = element("model.progress.qwen38-27b-splash")
        let advanced = NSPredicate(format: "value != nil AND value != %@", "0 percent downloaded")
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: advanced, object: progress)], timeout: 3), .completed)
        pause.click()
        let resume = element("model.resume.qwen38-27b-splash")
        XCTAssertTrue(resume.waitForExistence(timeout: 3))
        screenshot("synthetic-model-download-paused")
        resume.click()
        let use = element("model.use.qwen38-27b-splash")
        XCTAssertTrue(use.waitForExistence(timeout: 10))
        use.click()
        XCTAssertTrue(element("research.question").waitForExistence(timeout: 5))
    }

    @MainActor func testFirstUseDownloadResearchCancelHistoryAndCitations() {
        launch()
        defer { app.terminate() }
        XCTAssertTrue(element("synthetic-host-banner").waitForExistence(timeout: 10))
        screenshot("synthetic-first-use-light")
        setUpResearch()
        chooseSplashModel()
        let editor = element("research.question")
        XCTAssertTrue(editor.isHittable)
        editor.click()
        editor.typeText("Synthetic research question")
        element("research.network-consent").click()
        XCTAssertTrue(element("research.start").isEnabled)
        element("research.start").click()
        let stop = element("research.stop")
        XCTAssertTrue(stop.waitForExistence(timeout: 8))
        XCTAssertTrue(element("research.progress").exists)
        XCTAssertTrue(visibleText(element("research.progress")).contains("%"))
        XCTAssertNotEqual(visibleText(element("research.progress")), "0%")
        screenshot("synthetic-research-progress")
        stop.click()
        expectText("research.phase", equals: "Stopped", timeout: 8)
        element("history.synthetic-history").click()
        XCTAssertTrue(app.staticTexts["Synthetic history report"].waitForExistence(timeout: 5))
        XCTAssertEqual(visibleText(element("research.selected-query")), "Synthetic history question")
        XCTAssertTrue(app.staticTexts["Link unavailable: unsupported URL."].exists)
        XCTAssertEqual(app.webViews.count, 0)
        let source = element("source.link.0")
        XCTAssertTrue(source.exists)
        source.click()
        XCTAssertTrue(element("source-intercepted").waitForExistence(timeout: 3))
        screenshot("synthetic-report-citations")
        app.typeKey("n", modifierFlags: .command)
        XCTAssertTrue(element("research.question").waitForExistence(timeout: 3))
    }

    @MainActor func testModelDownloadErrorRetryAndDarkAppearance() {
        launch(arguments: ["--dark"])
        defer { app.terminate() }
        setUpResearch()
        app.buttons["Choose a model"].click()
        let second = element("model.download.qwen38-27b-uncensored")
        if !second.isHittable { element("models.scroll").scroll(byDeltaX: 0, deltaY: -450) }
        XCTAssertTrue(second.waitForExistence(timeout: 5))
        second.click()
        let retry = element("model.retry.qwen38-27b-uncensored")
        XCTAssertTrue(retry.waitForExistence(timeout: 5))
        if !retry.isHittable { element("models.scroll").scroll(byDeltaX: 0, deltaY: -200) }
        XCTAssertTrue(retry.isHittable)
        screenshot("synthetic-download-error-dark")
        retry.click()
        XCTAssertTrue(element("model.use.qwen38-27b-uncensored").waitForExistence(timeout: 10))
        let useSecond = element("model.use.qwen38-27b-uncensored")
        if !useSecond.isHittable { element("models.scroll").scroll(byDeltaX: 0, deltaY: -200) }
        XCTAssertTrue(useSecond.isHittable)
        screenshot("synthetic-model-chooser-dark")
        element("models.done").click()
        XCTAssertTrue(element("models.done").waitForNonExistence(timeout: 3))
        XCTAssertTrue(element("research.question").isHittable)
        app.buttons["Choose a model"].click()
        XCTAssertTrue(element("model.use.qwen38-27b-uncensored").waitForExistence(timeout: 3))
        app.typeKey(.escape, modifierFlags: [])
        XCTAssertTrue(element("models.done").waitForNonExistence(timeout: 3))
        XCTAssertTrue(element("research.question").isHittable)
    }

    @MainActor func testResearchErrorAndKeyboard() {
        launch(arguments: ["--research-failure"])
        defer { app.terminate() }
        setUpResearch()
        chooseSplashModel()
        element("research.question").click()
        element("research.question").typeText("Synthetic failing research question")
        element("research.network-consent").click()
        app.typeKey(.return, modifierFlags: .command)
        let error = app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@ OR value CONTAINS %@", "Synthetic research failure", "Synthetic research failure")).firstMatch
        XCTAssertTrue(error.waitForExistence(timeout: 5))
        XCTAssertTrue(element("research.question").isHittable)
        screenshot("synthetic-research-error-light")
    }

    @MainActor func testSuccessfulResearchReachesCompletedReport() {
        launch()
        defer { app.terminate() }
        setUpResearch()
        chooseSplashModel()
        element("research.question").click()
        element("research.question").typeText("Synthetic research completion")
        element("research.network-consent").click()
        app.typeKey(.return, modifierFlags: .command)
        expectText("research.phase", equals: "Completed", timeout: 25)
        XCTAssertTrue(app.staticTexts["Synthetic completed report"].waitForExistence(timeout: 5))
        XCTAssertTrue(element("research.stop").waitForNonExistence(timeout: 3))
        screenshot("synthetic-completed-report")
    }

    @MainActor func testQueuedModelCancelAndReopen() {
        launch(arguments: ["--slow-downloads"])
        defer { app.terminate() }
        setUpResearch()
        app.buttons["Choose a model"].click()
        element("model.download.qwen38-27b-splash").click()
        let second = element("model.download.qwen38-27b-uncensored")
        if !second.isHittable { element("models.scroll").scroll(byDeltaX: 0, deltaY: -450) }
        second.click()
        let cancel = element("model.cancel.qwen38-27b-uncensored")
        XCTAssertTrue(cancel.waitForExistence(timeout: 3))
        cancel.click()
        XCTAssertTrue(element("model.resume.qwen38-27b-uncensored").waitForExistence(timeout: 3))
        app.typeKey(.escape, modifierFlags: [])
        XCTAssertTrue(element("models.done").waitForNonExistence(timeout: 3))
        app.buttons["Choose a model"].click()
        XCTAssertTrue(element("model.resume.qwen38-27b-uncensored").waitForExistence(timeout: 3))
        screenshot("synthetic-queued-download-cancelled")
    }

    @MainActor func testWindowResizeKeepsOnboardingAccessible() throws {
        launch()
        defer { app.terminate() }
        XCTAssertTrue(element("synthetic-host-banner").waitForExistence(timeout: 10))
        let window = app.windows.firstMatch
        let before = window.frame
        let visible = try XCTUnwrap(NSScreen.main?.visibleFrame)
        XCTAssertGreaterThanOrEqual(before.minX, visible.minX)
        XCTAssertLessThanOrEqual(before.maxX, visible.maxX)
        guard before.width > 984 else { throw XCTSkip("Runner screen leaves no room above the host's minimum width; resize is not verified.") }
        let reduction = min(100, before.width - 984)
        let edge = window.coordinate(withNormalizedOffset: CGVector(dx: 1, dy: 0.5)).withOffset(CGVector(dx: -0.5, dy: 0))
        edge.click(forDuration: 0.6, thenDragTo: edge.withOffset(CGVector(dx: -reduction, dy: 0)))
        print("DEEPDESK_SYNTHETIC_RESIZE before=\(before) after=\(window.frame)")
        XCTAssertLessThan(window.frame.width, before.width)
        XCTAssertTrue(element("onboarding.consent").isHittable)
        screenshot("synthetic-onboarding-resized-light")
    }

}
