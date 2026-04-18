using System.Windows;

namespace JarvisHUD;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        var stateManager = new StateManager();
        var hud = new HUDWindow(stateManager);
        MainWindow = hud;
        hud.Show();

        var ipcClient = new IPCClient(stateManager);
        ipcClient.Connect();
    }
}

