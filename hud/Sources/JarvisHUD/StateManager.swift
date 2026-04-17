import Foundation
import Combine

enum JarvisState: String, Codable {
    case dormant
    case woke
    case listening
    case thinking
    case speaking
    case error
}

struct IPCMessage: Codable {
    let type: String
    var state: String?
    var text: String?
}

class StateManager: ObservableObject {
    @Published var state: JarvisState = .dormant
    @Published var transcript: String = ""

    func handleMessage(_ data: Data) {
        guard let msg = try? JSONDecoder().decode(
            IPCMessage.self, from: data
        ) else { return }

        DispatchQueue.main.async {
            switch msg.type {
            case "state":
                if let raw = msg.state,
                   let parsed = JarvisState(rawValue: raw)
                {
                    self.state = parsed
                }
            case "transcript":
                self.transcript = msg.text ?? ""
            default:
                break
            }
        }
    }
}
