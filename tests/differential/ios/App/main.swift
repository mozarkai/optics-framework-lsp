import UIKit

// A tree shaped to host every locator shape a real suite uses: chains deep enough to matter,
// repeated siblings so an index means something, identifiers that disagree with labels, and
// text fields so `@value` has something to match. The content is deliberately nothing:
// the harness asserts on structure, and inventing an app would only invite reading meaning
// into it.
final class RootController: UIViewController {
    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .white

        let stack = UIStackView()
        stack.axis = .vertical
        stack.spacing = 4
        stack.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
            stack.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 8),
            stack.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -8),
        ])

        // The second one's identifier and label disagree, which is what tells `@name`
        // (identifier or label) apart from `@identifier` and `@label`.
        for (index, title) in ["Alpha", "Bravo", "Charlie", "Delta"].enumerated() {
            let button = UIButton(type: .system)
            button.setTitle(title, for: .normal)
            button.accessibilityIdentifier = index == 1 ? "bravoButton" : title
            stack.addArrangedSubview(button)
        }
        for text in ["First label", "Second label", "Third label"] {
            let label = UILabel()
            label.text = text
            stack.addArrangedSubview(label)
        }

        // A deep container chain, for the long absolute paths a page source produces.
        var cursor = UIView()
        cursor.accessibilityIdentifier = "deep0"
        cursor.translatesAutoresizingMaskIntoConstraints = false
        cursor.heightAnchor.constraint(equalToConstant: 30).isActive = true
        stack.addArrangedSubview(cursor)
        for depth in 1..<18 {
            let next = UIView()
            next.accessibilityIdentifier = "deep\(depth)"
            next.translatesAutoresizingMaskIntoConstraints = false
            cursor.addSubview(next)
            NSLayoutConstraint.activate([
                next.topAnchor.constraint(equalTo: cursor.topAnchor),
                next.leadingAnchor.constraint(equalTo: cursor.leadingAnchor),
                next.widthAnchor.constraint(equalTo: cursor.widthAnchor),
                next.heightAnchor.constraint(equalTo: cursor.heightAnchor),
            ])
            cursor = next
        }
        let buried = UIButton(type: .system)
        buried.setTitle("Buried", for: .normal)
        buried.accessibilityIdentifier = "buriedButton"
        buried.frame = CGRect(x: 0, y: 0, width: 120, height: 30)
        cursor.addSubview(buried)

        // Two sibling containers of one type, each holding sibling fields, so an index on a
        // step that is not the last selects a different subtree.
        for group in 0..<2 {
            let box = UIView()
            box.accessibilityIdentifier = "group\(group)"
            box.translatesAutoresizingMaskIntoConstraints = false
            box.heightAnchor.constraint(equalToConstant: 84).isActive = true
            for slot in 0..<3 {
                let field = UITextField()
                field.borderStyle = .roundedRect
                field.accessibilityIdentifier = "g\(group)f\(slot)"
                field.text = "value \(group)\(slot)"
                field.frame = CGRect(x: 4, y: 4 + slot * 26, width: 280, height: 24)
                box.addSubview(field)
            }
            stack.addArrangedSubview(box)
        }

        let table = UITableView()
        table.accessibilityIdentifier = "rows"
        table.dataSource = self
        table.register(FieldCell.self, forCellReuseIdentifier: "c")
        table.translatesAutoresizingMaskIntoConstraints = false
        table.heightAnchor.constraint(equalToConstant: 200).isActive = true
        stack.addArrangedSubview(table)
    }
}

extension RootController: UITableViewDataSource {
    func tableView(_ table: UITableView, numberOfRowsInSection section: Int) -> Int { 4 }
    func tableView(_ table: UITableView, cellForRowAt at: IndexPath) -> UITableViewCell {
        let cell = table.dequeueReusableCell(withIdentifier: "c", for: at) as! FieldCell
        cell.field.accessibilityIdentifier = "field\(at.row)"
        cell.field.text = "row \(at.row)"
        return cell
    }
}

final class FieldCell: UITableViewCell {
    let field = UITextField()
    override init(style: UITableViewCell.CellStyle, reuseIdentifier: String?) {
        super.init(style: style, reuseIdentifier: reuseIdentifier)
        field.borderStyle = .roundedRect
        field.frame = CGRect(x: 8, y: 4, width: 300, height: 32)
        contentView.addSubview(field)
    }
    required init?(coder: NSCoder) { fatalError() }
}

final class AppDelegate: UIResponder, UIApplicationDelegate {
    var window: UIWindow?
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions options: [UIApplication.LaunchOptionsKey: Any]?
    ) -> Bool {
        window = UIWindow(frame: UIScreen.main.bounds)
        window?.rootViewController = RootController()
        window?.makeKeyAndVisible()
        return true
    }
}

UIApplicationMain(CommandLine.argc, CommandLine.unsafeArgv, nil, NSStringFromClass(AppDelegate.self))
