using System;
using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace JarvisHUD;

public enum JarvisState
{
    Dormant,
    Woke,
    Listening,
    Thinking,
    Speaking,
    Error
}

public record StatsSnapshot(
    string Time,
    string? Weather,
    float? Cpu,
    float? Ram,
    float? Disk,
    string Task);

public class StateManager : INotifyPropertyChanged
{
    private JarvisState _state = JarvisState.Dormant;
    private string _transcript = "";
    private StatsSnapshot _stats = new("--:--", null, null, null, null, "");

    public JarvisState State
    {
        get => _state;
        set { _state = value; OnPropertyChanged(); }
    }

    public string Transcript
    {
        get => _transcript;
        set { _transcript = value; OnPropertyChanged(); }
    }

    public StatsSnapshot Stats
    {
        get => _stats;
        private set { _stats = value; OnPropertyChanged(); }
    }

    public void HandleMessage(string json)
    {
        try
        {
            var msg = System.Text.Json.JsonSerializer.Deserialize<IPCMessage>(json);
            if (msg == null) return;

            System.Windows.Application.Current?.Dispatcher.Invoke(() =>
            {
                switch (msg.type)
                {
                    case "state":
                        if (Enum.TryParse<JarvisState>(msg.state, true, out var parsed))
                            State = parsed;
                        break;
                    case "transcript":
                        Transcript = msg.text ?? "";
                        break;
                    case "stats":
                        Stats = new StatsSnapshot(
                            msg.time ?? "--:--",
                            msg.weather,
                            msg.cpu,
                            msg.ram,
                            msg.disk,
                            msg.task ?? "");
                        break;
                }
            });
        }
        catch { /* ignore malformed messages */ }
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string? name = null)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}

public class IPCMessage
{
    public string type { get; set; } = "";
    public string? state { get; set; }
    public string? text { get; set; }
    public string? time { get; set; }
    public string? weather { get; set; }
    public float? cpu { get; set; }
    public float? ram { get; set; }
    public float? disk { get; set; }
    public string? task { get; set; }
}
