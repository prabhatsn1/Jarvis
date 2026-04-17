import SwiftUI

struct OrbView: View {
    @ObservedObject var stateManager: StateManager

    @State private var breatheScale: CGFloat = 1.0
    @State private var ringRotation: Double = 0
    @State private var glowOpacity: Double = 0.3
    @State private var pulseScale: CGFloat = 1.0

    private let orbSize: CGFloat = 80

    var body: some View {
        ZStack {
            // Outer glow
            Circle()
                .fill(stateColor.opacity(glowOpacity * 0.3))
                .frame(width: orbSize * 1.8, height: orbSize * 1.8)
                .blur(radius: 20)
                .scaleEffect(pulseScale)

            // Spinning ring (listening / thinking)
            if stateManager.state == .listening
                || stateManager.state == .thinking
            {
                Circle()
                    .strokeBorder(
                        AngularGradient(
                            colors: [
                                stateColor,
                                stateColor.opacity(0.2),
                                stateColor,
                            ],
                            center: .center
                        ),
                        lineWidth: 3
                    )
                    .frame(width: orbSize * 1.3, height: orbSize * 1.3)
                    .rotationEffect(.degrees(ringRotation))
            }

            // Core orb
            Circle()
                .fill(
                    RadialGradient(
                        colors: [
                            stateColor.opacity(0.9),
                            stateColor.opacity(0.4),
                        ],
                        center: .center,
                        startRadius: 0,
                        endRadius: orbSize / 2
                    )
                )
                .frame(width: orbSize, height: orbSize)
                .scaleEffect(breatheScale)
                .shadow(color: stateColor.opacity(0.5), radius: 15)

            // Inner specular highlight
            Circle()
                .fill(
                    RadialGradient(
                        colors: [.white.opacity(0.3), .clear],
                        center: UnitPoint(x: 0.35, y: 0.35),
                        startRadius: 0,
                        endRadius: orbSize / 3
                    )
                )
                .frame(width: orbSize * 0.7, height: orbSize * 0.7)
                .scaleEffect(breatheScale)
        }
        .frame(width: 200, height: 200)
        .onChange(of: stateManager.state) { _, newState in
            animateState(newState)
        }
        .onAppear {
            animateState(stateManager.state)
        }
    }

    // MARK: - State color

    private var stateColor: Color {
        switch stateManager.state {
        case .dormant:   return .cyan
        case .woke:      return .cyan
        case .listening: return .blue
        case .thinking:  return .purple
        case .speaking:  return .cyan
        case .error:     return .red
        }
    }

    // MARK: - Animations per state

    private func animateState(_ state: JarvisState) {
        // Reset ring
        withAnimation(.linear(duration: 0)) {
            ringRotation = 0
        }

        switch state {
        case .dormant:
            withAnimation(
                .easeInOut(duration: 4)
                    .repeatForever(autoreverses: true)
            ) {
                breatheScale = 1.05
                glowOpacity = 0.5
            }
            withAnimation(.easeInOut(duration: 0.3)) {
                pulseScale = 1.0
            }

        case .woke:
            withAnimation(.spring(response: 0.2, dampingFraction: 0.6)) {
                breatheScale = 1.2
                glowOpacity = 0.8
                pulseScale = 1.3
            }

        case .listening:
            withAnimation(
                .easeInOut(duration: 1)
                    .repeatForever(autoreverses: true)
            ) {
                breatheScale = 1.1
                glowOpacity = 0.7
            }
            withAnimation(
                .linear(duration: 3)
                    .repeatForever(autoreverses: false)
            ) {
                ringRotation = 360
            }

        case .thinking:
            withAnimation(
                .linear(duration: 1.5)
                    .repeatForever(autoreverses: false)
            ) {
                ringRotation = 360
            }
            withAnimation(
                .easeInOut(duration: 0.5)
                    .repeatForever(autoreverses: true)
            ) {
                breatheScale = 1.08
                glowOpacity = 0.6
                pulseScale = 1.1
            }

        case .speaking:
            withAnimation(
                .easeInOut(duration: 0.4)
                    .repeatForever(autoreverses: true)
            ) {
                breatheScale = 1.12
                glowOpacity = 0.7
                pulseScale = 1.15
            }

        case .error:
            withAnimation(
                .easeInOut(duration: 0.15)
                    .repeatCount(3, autoreverses: true)
            ) {
                glowOpacity = 1.0
                breatheScale = 1.15
            }
        }
    }
}
