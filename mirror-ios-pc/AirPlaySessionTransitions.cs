namespace XStageMirrorIOSPC;

// Video TCP can disconnect while the AirPlay control socket stays open.
// Require two consistent network samples to avoid short renegotiation blips.
internal sealed class AirPlaySessionTransitions
{
    private HashSet<string> _known = new(StringComparer.OrdinalIgnoreCase);
    private HashSet<string>? _candidate;
    private HashSet<string>? _hiddenAt;
    private int _samples;

    internal bool ShouldHide(string[] connections, bool showing)
    {
        var current = new HashSet<string>(connections, StringComparer.OrdinalIgnoreCase);
        if (!showing)
        {
            _candidate = null;
            _samples = 0;
            _known = current;
            return false;
        }
        if (_candidate is not null)
        {
            if (current.IsSubsetOf(_candidate))
            {
                _candidate = current;
                if (++_samples >= 2)
                {
                    _known = current;
                    _candidate = null;
                    _samples = 0;
                    return true;
                }
                return false;
            }
            _candidate = null;
            _samples = 0;
        }
        if (_known.Count > 0 && current.Count < _known.Count && current.IsSubsetOf(_known))
        {
            _candidate = current;
            _samples = 1;
        }
        _known = current;
        return false;
    }

    internal void MarkHidden(string[] connections)
    {
        _hiddenAt = new HashSet<string>(connections, StringComparer.OrdinalIgnoreCase);
        _known = new HashSet<string>(_hiddenAt, StringComparer.OrdinalIgnoreCase);
        _candidate = null;
        _samples = 0;
    }

    internal bool HasNewSession(string[] connections) =>
        _hiddenAt is not null && connections.Any(id => !_hiddenAt.Contains(id));

    internal void MarkVisible(string[] connections)
    {
        _hiddenAt = null;
        _known = new HashSet<string>(connections, StringComparer.OrdinalIgnoreCase);
        _candidate = null;
        _samples = 0;
    }

    internal void Reset()
    {
        _known.Clear();
        _hiddenAt = null;
        _candidate = null;
        _samples = 0;
    }
}
