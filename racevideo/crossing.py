"""Crossing interpolation for one already-associated wheel track.

Detection/identity and clock calibration remain separate. A bracket is evidence;
subframe interpolation is an estimate, never an extra captured frame.
"""
import math


def first_crossing(samples, max_clock_delta_ns=5_000_000):
    """Positive gap = tyre still before line; nonpositive = touching/past it.

    Samples carry ordinal, received_ns, monotonic_ns and gap_px. Call separately
    for each physical bike encounter. Missing frames retain a wider bracket but
    do not produce an interpolated timestamp. No result if footage starts past
    the line or no crossing is bracketed.
    """
    previous=None
    for current in samples:
        if not math.isfinite(current['gap_px']):raise ValueError('Invalid wheel/line distance')
        if previous is not None:
            if current['ordinal']<=previous['ordinal'] or current['monotonic_ns']<=previous['monotonic_ns']:
                raise ValueError('Wheel samples must follow source-frame order')
            if previous['gap_px']>0 and current['gap_px']<=0:
                frame_gap=current['ordinal']-previous['ordinal']
                mono_span=current['monotonic_ns']-previous['monotonic_ns']
                receipt_span=current['received_ns']-previous['received_ns']
                clock_jump=abs(receipt_span-mono_span)>max_clock_delta_ns
                fraction=previous['gap_px']/(previous['gap_px']-current['gap_px'])
                status='clock_discontinuity' if clock_jump else 'missing_frames' if frame_gap!=1 else 'interpolated'
                estimate=previous['received_ns']+round(receipt_span*fraction) if status=='interpolated' else None
                return dict(status=status,before_ordinal=previous['ordinal'],
                  first_observed_after_ordinal=current['ordinal'],
                  before_received_ns=previous['received_ns'],after_received_ns=current['received_ns'],
                  frame_gap=frame_gap,bracket_monotonic_ns=mono_span,
                  fraction_between_frames=fraction if status=='interpolated' else None,
                  estimated_received_ns=estimate,
                  timestamp_basis='host receipt times; exposure/USB/readout offset uncalibrated',
                  before_source_pts=previous.get('source_pts'),before_time_base=previous.get('time_base'),
                  after_source_pts=current.get('source_pts'),after_time_base=current.get('time_base'))
        previous=current
    return None
