import Foundation

class IPCClient {
    private let socketPath = "/tmp/jarvis.sock"
    private let stateManager: StateManager
    private var fileHandle: FileHandle?

    init(stateManager: StateManager) {
        self.stateManager = stateManager
    }

    func connect() {
        DispatchQueue.global(qos: .utility).async { [weak self] in
            self?.connectLoop()
        }
    }

    // MARK: - Connection loop

    private func connectLoop() {
        while true {
            let fd = socket(AF_UNIX, SOCK_STREAM, 0)
            guard fd >= 0 else {
                sleep(2)
                continue
            }

            var addr = sockaddr_un()
            addr.sun_family = sa_family_t(AF_UNIX)

            // Copy socket path into sun_path
            socketPath.withCString { cstr in
                withUnsafeMutableBytes(of: &addr.sun_path) { buf in
                    let len = min(strlen(cstr), buf.count - 1)
                    memcpy(buf.baseAddress!, cstr, len)
                }
            }

            let connected = withUnsafePointer(to: &addr) { ptr in
                ptr.withMemoryRebound(
                    to: sockaddr.self, capacity: 1
                ) { sockPtr in
                    Darwin.connect(
                        fd, sockPtr,
                        socklen_t(MemoryLayout<sockaddr_un>.size)
                    )
                }
            }

            if connected < 0 {
                Darwin.close(fd)
                sleep(2)
                continue
            }

            fileHandle = FileHandle(
                fileDescriptor: fd, closeOnDealloc: true
            )
            readLoop()
            // Connection lost — retry
        }
    }

    // MARK: - Read loop

    private func readLoop() {
        guard let fh = fileHandle else { return }
        var buffer = Data()

        while true {
            let chunk = fh.availableData
            if chunk.isEmpty { break } // EOF — connection closed

            buffer.append(chunk)

            // Process newline-delimited JSON messages
            while let idx = buffer.firstIndex(of: UInt8(ascii: "\n")) {
                let lineData = buffer[buffer.startIndex..<idx]
                buffer = Data(buffer[buffer.index(after: idx)...])
                stateManager.handleMessage(Data(lineData))
            }
        }
    }
}
