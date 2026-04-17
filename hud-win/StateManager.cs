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

public class StateManager : INotifyPropertyChanged
{
    private JarvisState _state = JarvisState.Dormant;
    private string _transcript = "";

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
}
