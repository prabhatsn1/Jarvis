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

struct StatsSnapshot {
    var time: String
    var weather: String?
    var cpu: Float?
    var ram: Float?
    var disk: Float?
    var task: String?
}

struct IPCMessage: Codable {
    let type: String
    var state: String?
    var text: String?
    var time: String?
    var weather: String?
    var cpu: Float?
    var ram: Float?
    var disk: Float?
    var task: String?
}

class StateManager: ObservableObject {
    @Published var state: JarvisState = .dormant
    @Published var transcript: String = ""
    @Published var stats: StatsSnapshot = StatsSnapshot(time: "--:--")

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
            case "stats":
                self.stats = StatsSnapshot(
                    time:    msg.time ?? "--:--",
                    weather: msg.weather,
                    cpu:     msg.cpu,
                    ram:     msg.ram,
                    disk:    msg.disk,
                    task:    msg.task
                )
            default:
                break
            }
        }
    }
}
