import AppKit

/// Soft two-note chimes for starting and stopping listening. The system alert sound (NSSound.beep)
/// reads as "something went wrong", so these are synthesised: quiet sine tones with smooth edges.
enum Chime {
    private static let start = tone([659.3, 987.8])  // E5 → B5, rising: "listening"
    private static let stop = tone([987.8, 659.3])  // falling: "done listening"

    static func playStart() { play(start) }
    static func playStop() { play(stop) }

    private static func play(_ sound: NSSound?) {
        guard let sound else { return }
        sound.stop()
        sound.play()
    }

    private static func tone(_ frequencies: [Double], note: Double = 0.075, volume: Double = 0.16) -> NSSound? {
        let rate = 44_100.0
        var samples: [Int16] = []
        for frequency in frequencies {
            let count = Int(rate * note)
            for index in 0..<count {
                let envelope = sin(Double.pi * Double(index) / Double(count))  // fades in and out
                let value = sin(2 * Double.pi * frequency * Double(index) / rate) * envelope * volume
                samples.append(Int16(value * Double(Int16.max)))
            }
        }
        return NSSound(data: wav(samples, rate: Int(rate)))
    }

    private static func wav(_ samples: [Int16], rate: Int) -> Data {
        var data = Data()
        func append<T: FixedWidthInteger>(_ value: T) {
            withUnsafeBytes(of: value.littleEndian) { data.append(contentsOf: $0) }
        }
        let bytes = samples.count * 2
        data.append(contentsOf: Array("RIFF".utf8)); append(UInt32(36 + bytes))
        data.append(contentsOf: Array("WAVE".utf8))
        data.append(contentsOf: Array("fmt ".utf8)); append(UInt32(16)); append(UInt16(1)); append(UInt16(1))
        append(UInt32(rate)); append(UInt32(rate * 2)); append(UInt16(2)); append(UInt16(16))
        data.append(contentsOf: Array("data".utf8)); append(UInt32(bytes))
        samples.forEach { append($0) }
        return data
    }
}
