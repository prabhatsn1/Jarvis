using System;
using System.IO;
using System.IO.Pipes;
using System.Threading;

namespace JarvisHUD;

public class IPCClient
{
    private readonly StateManager _stateManager;

    public IPCClient(StateManager stateManager)
    {
        _stateManager = stateManager;
    }

    public void Connect()
    {
        var thread = new Thread(ConnectLoop)
        {
            IsBackground = true,
            Name = "JarvisIPC"
        };
        thread.Start();
    }

    private void ConnectLoop()
    {
        while (true)
        {
            try
            {
                using var pipe = new NamedPipeClientStream(
                    ".", "jarvis", PipeDirection.In
                );

                pipe.Connect(2000);

                using var reader = new StreamReader(pipe);
                while (!reader.EndOfStream)
                {
                    var line = reader.ReadLine();
                    if (!string.IsNullOrWhiteSpace(line))
                    {
                        _stateManager.HandleMessage(line);
                    }
                }
            }
            catch (TimeoutException)
            {
                // Core not running yet — retry
            }
            catch (IOException)
            {
                // Connection lost — retry
            }
            catch (Exception)
            {
                // Unexpected — retry after delay
            }

            Thread.Sleep(2000);
        }
    }
}
