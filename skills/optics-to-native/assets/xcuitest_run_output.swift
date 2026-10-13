// iOS step 7 (references/run-output.md): copy the parts into the file built from
// xcuitest_example.swift. This file is not compiled on its own. Replace the `errors` entries with the
// suite's error definitions (an empty array when it has none).
//
// How a case runs: XCTest cannot catch a failed assertion, and by default stops the test method at
// the first one. That is what optics does too (a failing step stops the test case), so a failure is
// simply let through. `record(_:)` notes its message, and `tearDownWithError` - which XCTest still
// runs after a failure - turns the case into a report entry and marks the modules that never ran.

// --- Part 1: members of the test class, after `var soft` ---------------------------------------
// `BUNDLE_ID` is the config's `bundleId` (with no `bundleId`, make `setUpWithError` use
// `XCUIApplication()`); `STEP_DELAY` and the wait settings are read once, here.

    let BUNDLE_ID = "com.example.app"
    let STEP_DELAY = Double(ProcessInfo.processInfo.environment["OPTICS_STEP_DELAY"] ?? "") ?? 0.1
    // Replace the example's `let IMPLICIT_WAIT = 20.0` with:
    //     let IMPLICIT_WAIT = Double(ProcessInfo.processInfo.environment["OPTICS_WAIT_TIMEOUT"] ?? "") ?? 20.0
    // and the sleep in `waitUntil` with `Thread.sleep(forTimeInterval: POLL_INTERVAL)`:
    let POLL_INTERVAL = Double(ProcessInfo.processInfo.environment["OPTICS_POLL_INTERVAL"] ?? "") ?? 0.3

    static var results: [[String: Any]] = []
    static var detected: [[String: Any]] = []
    static var suiteStart = ""
    static var suiteBegan = Date()
    static let session = ProcessInfo.processInfo.environment["SESSION_ID"] ?? stamp("yyyyMMddHHmmss")

    let errors: [(code: String, match: String, description: String, severity: String)] = [
        (code: "E_SESSION", match: "Session expired", description: "Kicked back to the login screen", severity: "high"),
    ]

    var caseName = ""
    var caseStart = ""
    var caseBegan = Date()
    var plan: [(name: String, owner: String)] = []
    var entries: [[String: Any]] = []
    var running: (index: Int, start: String, began: Date)? = nil
    var failure: String? = nil
    var failureStatus = "FAIL"
    var finished = false
    var swallowing = 0  // inside `ok(...)`, where a failure is an answer, not a result
    var at = ""

// --- Part 2: replaces `setUpWithError` and `tearDownWithError`; the helpers go in the class ----

    override class func setUp() {
        suiteStart = stamp()
        suiteBegan = Date()
    }

    override class func tearDown() {
        writeReports()
    }

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication(bundleIdentifier: BUNDLE_ID)
    }

    override func tearDownWithError() throws {
        if !soft.isEmpty && soft.contains(false) {
            print("soft checks: \(soft.filter { $0 }.count) of \(soft.count) passed")
        }
        finishCase()
    }

    // MARK: run output

    static func stamp(_ format: String = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS") -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = format
        return formatter.string(from: Date())
    }

    func seconds(_ since: Date) -> String { return String(format: "%.6f", Date().timeIntervalSince(since)) }

    static var out: URL {
        let base = ProcessInfo.processInfo.environment["EXEC_OUTPUT"] ?? (NSTemporaryDirectory() + "output")
        let url = URL(fileURLWithPath: base)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    /// Before each step: where it came from, for a failure to name.
    func origin(_ where_: String) {
        at = where_
        Thread.sleep(forTimeInterval: STEP_DELAY)
    }

    /// First line only: XCTest's element messages list the whole screen.
    override func record(_ issue: XCTIssue) {
        if !finished && failure == nil && swallowing == 0 {
            let first = issue.compactDescription.components(separatedBy: "\n").first ?? ""
            failure = at.isEmpty ? first : "\(at): \(first)"
            failureStatus = issue.type == .assertionFailure ? "FAIL" : "ERROR"
        }
        super.record(issue)
    }

    /// A screenshot is evidence, never a reason to fail a step: the app may be closed by then.
    func post(_ keyword: String) {
        let flag = (ProcessInfo.processInfo.environment["ENABLE_POST_SCREENSHOT"] ?? "1").lowercased()
        if ["0", "false", "no"].contains(flag) { return }
        let shot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: shot)
        attachment.lifetime = .keepAlways
        add(attachment)
        if let data = shot.image.jpegData(compressionQuality: 0.8) {
            let name = "post-\(Self.stamp("yyyy-MM-dd'T'HH-mm-ss-SSSSSS"))-\(keyword).jpg"
            try? data.write(to: Self.out.appendingPathComponent(name))
        }
    }

    /// Every element's `name`, `label` and `value`, lowercased, as the page-source text optics reads.
    func pageText() -> String {
        guard let root = snapshotTree() else { return "" }
        var parts: [String] = []
        func walk(_ node: Node) {
            for text in [node.name, node.label, node.value] where !text.isEmpty { parts.append(text) }
            node.children.forEach(walk)
        }
        walk(root)
        return parts.joined(separator: " ").lowercased()
    }

    /// Declare the test case and its modules, in order, before the first `step`.
    func begin(_ name: String, _ modules: [(String, String)]) {
        caseName = name
        plan = modules.map { (name: $0.0, owner: $0.1) }
        caseStart = Self.stamp()
        caseBegan = Date()
    }

    /// One module of the test case. A failure inside it ends the test method; `finishCase`
    /// finds `running` still set and records that module as the failed one.
    func step(_ name: String, _ owner: String, _ module: () -> Void) {
        let index = entries.count
        running = (index: index, start: Self.stamp(), began: Date())
        module()
        entries.append(entry(index, "PASS"))
        running = nil
    }

    func entry(_ index: Int, _ status: String) -> [String: Any] {
        let start = running?.start ?? Self.stamp()
        let began = running?.began ?? Date()
        return ["name": plan[index].name, "status": status, "type": "step", "start": start,
                "end": Self.stamp(), "duration": seconds(began), "testSuite": "Test Cases",
                "testCase": caseName, "owner": "OpticsKeywords." + plan[index].owner, "subSteps": []]
    }

    /// End of every test case, passed or not: error-code detection, then the case's result.
    func finishCase() {
        if caseName.isEmpty || finished { return }
        if failure != nil, let current = running { entries.append(entry(current.index, failureStatus)) }
        for index in entries.count..<max(entries.count, plan.count) {
            running = nil
            var skipped = entry(index, "NOT RUN")
            skipped["duration"] = "0.000000"
            entries.append(skipped)
        }
        var status = failure == nil ? "PASS" : failureStatus
        var reason = failure ?? "Test completed successfully"
        let text = pageText()
        let found = errors.filter { text.contains($0.match.lowercased()) || text.contains($0.code.lowercased()) }
        if !found.isEmpty {
            for error in found {
                Self.detected.append(["error_code": error.code,
                                      "matched_on": text.contains(error.match.lowercased()) ? "match_string" : "code",
                                      "match_string": error.match, "description": error.description,
                                      "severity": error.severity, "detected_at": "end_of_test", "test_case": caseName])
            }
            Self.writeDetected()
            status = "FAIL"
            reason = found.map { "\($0.code): \($0.description.isEmpty ? $0.match : $0.description)" }.joined(separator: "; ")
        }
        if status != "PASS" { post("failure") }
        Self.results.append(["name": caseName, "status": status, "type": "testCase", "testSuite": "Test Cases",
                             "start": caseStart, "end": Self.stamp(), "duration": seconds(caseBegan),
                             "id": "s1-s1-s1-s1-s1-t\(Self.results.count + 1)", "reason": reason, "steps": entries])
        finished = true
        if failure == nil && status != "PASS" { XCTFail(reason) }
    }

    static func writeDetected() {
        let body: [String: Any] = ["timestamp": String(stamp().prefix(19)), "detected": detected]
        if let data = try? JSONSerialization.data(withJSONObject: body, options: [.prettyPrinted]) {
            try? data.write(to: out.appendingPathComponent("detected_errors_\(session).json"))
        }
    }

    static func writeReports() {
        let passed = results.allSatisfy { ($0["status"] as? String) == "PASS" }
        let suite: [String: Any] = ["name": "Test Cases", "status": passed ? "PASS" : "FAIL", "type": "testSuite",
                                    "start": suiteStart, "end": stamp(),
                                    "duration": String(format: "%.6f", Date().timeIntervalSince(suiteBegan)),
                                    "id": "s1-s1-s1-s1-s1", "appVersion": NSNull(), "testCases": results]
        if let data = try? JSONSerialization.data(withJSONObject: ["testSuites": [suite]], options: [.prettyPrinted]) {
            try? data.write(to: out.appendingPathComponent("test_report.json"))
        }
        func escaped(_ text: String) -> String {
            return text.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
                .replacingOccurrences(of: ">", with: "&gt;").replacingOccurrences(of: "\"", with: "&quot;")
        }
        let failures = results.filter { ($0["status"] as? String) == "FAIL" }.count
        let errored = results.filter { ($0["status"] as? String) == "ERROR" }.count
        var xml = "<?xml version='1.0' encoding='utf-8'?>\n<testsuites><testsuite tests=\"\(results.count)\" failures=\"\(failures)\" errors=\"\(errored)\" skipped=\"0\" time=\"\(suite["duration"] as! String)\">\n"
        for result in results {
            let status = result["status"] as? String ?? ""
            xml += "<testcase name=\"\(escaped(result["name"] as? String ?? ""))\" classname=\"Test Cases\" time=\"\(result["duration"] as? String ?? "0")\""
            let reason = escaped(result["reason"] as? String ?? "")
            switch status {
            case "FAIL": xml += "><failure message=\"\(reason)\" /></testcase>\n"
            case "ERROR": xml += "><error message=\"\(reason)\" /></testcase>\n"
            default: xml += " />\n"
            }
        }
        xml += "</testsuite></testsuites>\n"
        try? xml.write(to: out.appendingPathComponent("junit-results.xml"), atomically: true, encoding: .utf8)
    }

// --- Part 3: a test case, in `// MARK: test cases`; the number keeps XCTest's alphabetical order = suite order

    /// Login
    func test01Login() {
        begin("Login", [("Open App", "AppManagement"), ("Sign In", "ActionKeywords")])
        step("Open App", "AppManagement") { openApp() }  // test_cases.csv:2
        step("Sign In", "ActionKeywords") { signIn() }  // test_cases.csv:3
    }
