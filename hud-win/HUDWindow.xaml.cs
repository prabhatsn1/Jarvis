using System.Collections.Generic;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace JarvisHUD;

public partial class HUDWindow : Window
{
    private readonly StateManager _stateManager;
    private Storyboard? _currentStoryboard;

    private static readonly Color CyanColor   = (Color)ColorConverter.ConvertFromString("#00CED1");
    private static readonly Color BlueColor   = (Color)ColorConverter.ConvertFromString("#4169E1");
    private static readonly Color PurpleColor = (Color)ColorConverter.ConvertFromString("#8A2BE2");
    private static readonly Color GreenColor  = (Color)ColorConverter.ConvertFromString("#00C853");
    private static readonly Color RedColor    = (Color)ColorConverter.ConvertFromString("#FF4444");

    public HUDWindow(StateManager stateManager)
    {
        InitializeComponent();
        _stateManager = stateManager;

        // Position: bottom-center of primary screen
        var screen = SystemParameters.WorkArea;
        Left = screen.Left + (screen.Width - Width) / 2;
        Top  = screen.Top  + screen.Height - Height - 60;

        _stateManager.PropertyChanged += (s, e) =>
        {
            if (e.PropertyName == nameof(StateManager.State))
                AnimateState(_stateManager.State);
            else if (e.PropertyName == nameof(StateManager.Stats))
                UpdateStats(_stateManager.Stats);
        };

        Loaded += (s, e) => AnimateState(JarvisState.Dormant);
    }

    private void Window_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        DragMove();
    }

    // ── Stats display ──────────────────────────────────────────

    private void UpdateStats(StatsSnapshot stats)
    {
        TimeText.Text    = stats.Time;
        WeatherText.Text = stats.Weather ?? "";
        HealthText.Text  = (stats.Cpu.HasValue || stats.Ram.HasValue)
            ? $"CPU {stats.Cpu:F0}%  RAM {stats.Ram:F0}%"
            : "";
        TaskText.Text = stats.Task;
    }

    private void UpdateStatsColor(Color c)
    {
        TimeText.Foreground    = new SolidColorBrush(Color.FromArgb(200, c.R, c.G, c.B));
        WeatherText.Foreground = new SolidColorBrush(Color.FromArgb(153, c.R, c.G, c.B));
        HealthText.Foreground  = new SolidColorBrush(Color.FromArgb(153, c.R, c.G, c.B));
        TaskText.Foreground    = new SolidColorBrush(Color.FromArgb(119, c.R, c.G, c.B));
    }

    // ── Animations ─────────────────────────────────────────────

    private void AnimateState(JarvisState state)
    {
        _currentStoryboard?.Stop(this);

        var sb = new Storyboard();

        WaveRing1.Visibility = Visibility.Collapsed;
        WaveRing2.Visibility = Visibility.Collapsed;

        switch (state)
        {
            case JarvisState.Dormant:
                SpinRing.Visibility = Visibility.Collapsed;
                SetOrbColor(CyanColor);
                AddBreathe(sb, OrbScale, 1.0, 1.05, TimeSpan.FromSeconds(4));
                AddFade(sb, OuterGlow, 0.15, 0.3, TimeSpan.FromSeconds(4));
                break;

            case JarvisState.Woke:
                SpinRing.Visibility = Visibility.Collapsed;
                SetOrbColor(CyanColor);
                AddSnap(sb, OrbScale, 1.2, TimeSpan.FromMilliseconds(200));
                AddFade(sb, OuterGlow, 0.15, 0.6, TimeSpan.FromMilliseconds(200));
                break;

            case JarvisState.Listening:
                SpinRing.Visibility = Visibility.Visible;
                SetOrbColor(BlueColor);
                SetRingColor(BlueColor);
                AddSpin(sb, RingRotation, TimeSpan.FromSeconds(3));
                AddBreathe(sb, OrbScale, 1.0, 1.1, TimeSpan.FromSeconds(1));
                AddFade(sb, OuterGlow, 0.2, 0.5, TimeSpan.FromSeconds(1));
                break;

            case JarvisState.Thinking:
                SpinRing.Visibility = Visibility.Visible;
                SetOrbColor(PurpleColor);
                SetRingColor(PurpleColor);
                AddSpin(sb, RingRotation, TimeSpan.FromSeconds(1.5));
                AddBreathe(sb, OrbScale, 1.0, 1.08, TimeSpan.FromMilliseconds(500));
                AddFade(sb, OuterGlow, 0.2, 0.45, TimeSpan.FromMilliseconds(500));
                break;

            case JarvisState.Speaking:
                SpinRing.Visibility = Visibility.Collapsed;
                WaveRing1.Visibility = Visibility.Visible;
                WaveRing2.Visibility = Visibility.Visible;
                SetOrbColor(GreenColor);
                WaveRing1.Stroke = new SolidColorBrush(Color.FromArgb(180, GreenColor.R, GreenColor.G, GreenColor.B));
                WaveRing2.Stroke = new SolidColorBrush(Color.FromArgb(180, GreenColor.R, GreenColor.G, GreenColor.B));
                AddBreathe(sb, OrbScale, 1.0, 1.08, TimeSpan.FromMilliseconds(400));
                AddFade(sb, OuterGlow, 0.25, 0.5, TimeSpan.FromMilliseconds(400));
                AddWave(sb, WaveScale1, WaveRing1, TimeSpan.Zero);
                AddWave(sb, WaveScale2, WaveRing2, TimeSpan.FromMilliseconds(600));
                break;

            case JarvisState.Error:
                SpinRing.Visibility = Visibility.Collapsed;
                SetOrbColor(RedColor);
                AddFlash(sb, OuterGlow, TimeSpan.FromMilliseconds(150), 3);
                break;
        }

        _currentStoryboard = sb;
        sb.Begin(this, true);

        UpdateStatsColor(StateColor(state));
    }

    private static Color StateColor(JarvisState state) => state switch
    {
        JarvisState.Listening => BlueColor,
        JarvisState.Thinking  => PurpleColor,
        JarvisState.Speaking  => GreenColor,
        JarvisState.Error     => RedColor,
        _                     => CyanColor,
    };

    // ── Helpers ────────────────────────────────────────────────

    private void SetOrbColor(Color color)
    {
        OrbColorInner.Color = Color.FromArgb(230, color.R, color.G, color.B);
        OrbColorOuter.Color = Color.FromArgb(102, color.R, color.G, color.B);
    }

    private void SetRingColor(Color color)
    {
        SpinRing.Stroke = new LinearGradientBrush(
            color,
            Color.FromArgb(48, color.R, color.G, color.B),
            new Point(0, 0), new Point(1, 1)
        );
    }

    private static void AddBreathe(Storyboard sb, ScaleTransform target,
        double from, double to, TimeSpan duration)
    {
        var animX = new DoubleAnimation(from, to, duration)
        {
            AutoReverse = true,
            RepeatBehavior = RepeatBehavior.Forever,
            EasingFunction = new SineEase()
        };
        var animY = animX.Clone();

        Storyboard.SetTarget(animX, target);
        Storyboard.SetTargetProperty(animX, new PropertyPath(ScaleTransform.ScaleXProperty));
        Storyboard.SetTarget(animY, target);
        Storyboard.SetTargetProperty(animY, new PropertyPath(ScaleTransform.ScaleYProperty));

        sb.Children.Add(animX);
        sb.Children.Add(animY);
    }

    private static void AddSnap(Storyboard sb, ScaleTransform target,
        double to, TimeSpan duration)
    {
        var animX = new DoubleAnimation(to, duration)
        {
            EasingFunction = new ElasticEase { Oscillations = 1, Springiness = 8 }
        };
        var animY = animX.Clone();

        Storyboard.SetTarget(animX, target);
        Storyboard.SetTargetProperty(animX, new PropertyPath(ScaleTransform.ScaleXProperty));
        Storyboard.SetTarget(animY, target);
        Storyboard.SetTargetProperty(animY, new PropertyPath(ScaleTransform.ScaleYProperty));

        sb.Children.Add(animX);
        sb.Children.Add(animY);
    }

    private static void AddFade(Storyboard sb, UIElement target,
        double from, double to, TimeSpan duration)
    {
        var anim = new DoubleAnimation(from, to, duration)
        {
            AutoReverse = true,
            RepeatBehavior = RepeatBehavior.Forever,
            EasingFunction = new SineEase()
        };

        Storyboard.SetTarget(anim, target);
        Storyboard.SetTargetProperty(anim, new PropertyPath(UIElement.OpacityProperty));
        sb.Children.Add(anim);
    }

    private static void AddSpin(Storyboard sb, RotateTransform target, TimeSpan duration)
    {
        var anim = new DoubleAnimation(0, 360, duration)
        {
            RepeatBehavior = RepeatBehavior.Forever
        };

        Storyboard.SetTarget(anim, target);
        Storyboard.SetTargetProperty(anim, new PropertyPath(RotateTransform.AngleProperty));
        sb.Children.Add(anim);
    }

    private static void AddFlash(Storyboard sb, UIElement target,
        TimeSpan interval, int count)
    {
        var anim = new DoubleAnimation(0.2, 1.0, interval)
        {
            AutoReverse = true,
            RepeatBehavior = new RepeatBehavior(count)
        };

        Storyboard.SetTarget(anim, target);
        Storyboard.SetTargetProperty(anim, new PropertyPath(UIElement.OpacityProperty));
        sb.Children.Add(anim);
    }

    private static void AddWave(Storyboard sb, ScaleTransform scaleTarget,
        UIElement opacityTarget, TimeSpan beginTime)
    {
        var duration = TimeSpan.FromSeconds(1.0);

        var scaleX = new DoubleAnimation(1.0, 2.2, duration)
        {
            BeginTime = beginTime,
            RepeatBehavior = RepeatBehavior.Forever,
            EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
        };
        var scaleY = scaleX.Clone();

        Storyboard.SetTarget(scaleX, scaleTarget);
        Storyboard.SetTargetProperty(scaleX, new PropertyPath(ScaleTransform.ScaleXProperty));
        Storyboard.SetTarget(scaleY, scaleTarget);
        Storyboard.SetTargetProperty(scaleY, new PropertyPath(ScaleTransform.ScaleYProperty));

        var fade = new DoubleAnimation(0.7, 0.0, duration)
        {
            BeginTime = beginTime,
            RepeatBehavior = RepeatBehavior.Forever,
            EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
        };

        Storyboard.SetTarget(fade, opacityTarget);
        Storyboard.SetTargetProperty(fade, new PropertyPath(UIElement.OpacityProperty));

        sb.Children.Add(scaleX);
        sb.Children.Add(scaleY);
        sb.Children.Add(fade);
    }
}
