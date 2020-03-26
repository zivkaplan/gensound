# -*- coding: utf-8 -*-
"""
Created on Sun Aug 18 21:01:16 2019

@author: Dror
"""

import numpy as np
from curve import Curve, Line, Logistic, Constant
from audio import Audio
from utils import lambda_to_range, DB_to_Linear, \
                  isnumber, iscallable, \
                  num_samples, samples_slice

class Transform:
    """ represents post-processing on some given signal.
    use __init__ to set the transform params,
    and realise for the implementation on the WAV.
    
    realise should directly change the audio of the signal element,
    and thus each transform can be bound to several signals without intereference.
    
    """
    
    def __init__(self):
        # TODO consider using *kwargs and making it copy all attributes to self
        # this would save us many inherited inits simply doing self.duration = duration
        # OTOH could this break something by name collision?
        # also, wouldn't this make the code less clear (note that num_samples() also
        # uses hidden self.duration)
        pass
    
    def __str__(self):
        return str(type(self).__name__)
    
    def num_samples(self, sample_rate):
        if not hasattr(self, "duration"):
            raise TypeError("transform.duration must be defined to support conversion to samples")
        return num_samples(self.duration, sample_rate)
    
    def realise(self, audio):
        """ here we apply the transformation on the Audio object.
        this should change the object directly, don't return anything."""
        pass


####### Basic shape stuff ##############

class Shift(Transform):
    """ shifts the signal forward in time."""
    # TODO enable backword
    def __init__(self, duration=None, samples=None):
        # TODO perhaps infer duration/samples by float/int?
        # Or maybe split into 2 classes, just to prevent confusion
        assert isnumber(duration) + isnumber(samples) == 1, "too many/too few arguments to Shift()"
        self.duration = duration
        self.samples = samples
    
    def realise(self, audio):
        samples = self.samples if isnumber(self.samples) else self.num_samples(audio.sample_rate)
        audio.push_forward(samples)

class Extend(Transform):
    """ adds silence after the signal. needed?
    """
    def __init__(self, duration):
        self.duration = duration
    
    def realise(self, audio):
        audio.extend(self.num_samples(audio.sample_rate))

class Reverse(Transform):
    """
    reverses the signal
    """
    def realise(self, audio):
        audio.audio[:,:] = audio.audio[:,::-1]

class Slice(Transform):
    """ returns only a specified part of the signal.
    Should not be invoked by the user, rather it is used by
    Signal.__getitem.
    
    # TODO if hell froze over maybe its possible to merge this with Combine
    """
    def __init__(self, channel_slice, time_slice):
        # TODO filter slices (if relevant?)
        self.channel_slice = channel_slice
        self.time_slice = time_slice
    
    def realise(self, audio):
        if audio.is_mono() and self.channel_slice.start == 0 and self.channel_slice.stop > 0:
            audio.from_mono(self.channel_slice.stop)
        audio.audio = audio.audio[self.channel_slice,
                                  samples_slice(self.time_slice, audio.sample_rate)]
        assert audio.ensure_2d(), "pbbly channel_slice wasn't a slice, so not ensure_2d()"

class Combine(Transform):
    """ given another Signal as input, realises it and pushes it back
    into the affected signal in the relevant place.
    if the signal to push inside is too small, it will mean a silence gap,
    if too long, its remainder will be mixed into the continuation of the parent signal
    Should not be invoked by the user, rather it is used by
    Signal.__getitem.
    """
    def __init__(self, channel_slice, time_slice, signal):
        self.channel_slice = channel_slice
        self.time_slice = time_slice
        self.signal = signal
    
    def realise(self, audio):
        # locating correct samples
        sample_slice = samples_slice(self.time_slice, audio.sample_rate)
        
        # add channels in case of out-of-bounds channel subscript
        max_channel = max(0, self.channel_slice.start or 0, (self.channel_slice.stop or 0)-1)
        if max_channel >= audio.num_channels():
            audio.to_channels(max_channel+1)
            
        
        # preparing new audio
        new_audio = self.signal.realise(audio.sample_rate)
        
        # putting the new audio in
        audio.audio[self.channel_slice, sample_slice] = 0 # TODO is this needed?
        start_sample = sample_slice.start if sample_slice.start is not None else 0
        audio.to_length(start_sample + new_audio.length())
        audio.audio[self.channel_slice, start_sample:start_sample+new_audio.length()] += new_audio.audio


######### Level/ampltidue Stuff ###################

class Fade(Transform):
    min_fade = -50
    
    def __init__(self, is_in=True, duration=3000):
        self.is_in = is_in
        self.duration = duration
    
    def realise(self, audio):
        amp = DB_to_Linear(np.linspace(Fade.min_fade, 0, self.num_samples(audio.sample_rate)))
        # perhaps the fade in should be nonlinear
        # TODO subsciprability problem
        
        if not self.is_in:
            amp[:] = amp[::-1]
        
        # TODO in case of fade out, if amp is shorter or longer than audio,
        # care must be taken when multiplying!
        audio *= amp
        # TODO TEST!!!!!!!!!!!!!
        # TODO I still hear a bump when the playback starts


class Gain(Transform):
    """
    Adds positive/negative gain in dBs to the signal.
    """
    def __init__(self, *dBs):
        self.dBs = dBs
    
    def realise(self, audio):
        # should we make this inherit from amplitude? like Triangle/Sine relation?
        for (i, dB) in enumerate(self.dBs):
            if isnumber(dB):
                audio.audio[i,:] *= DB_to_Linear(dB)
            elif isinstance(dB, Curve):
                vals = DB_to_Linear(dB.flatten(audio.sample_rate))
                audio.audio[i,0:dB.num_samples(audio.sample_rate)] *= vals
                audio.audio[i,dB.num_samples(audio.sample_rate):] *= DB_to_Linear(dB.endpoint())
            else:
                raise TypeError("Unsupported amplitude type")

class Amplitude(Transform):
    """ simple increase/decrease of amplitude.
    for constant amplitude, don't use this directly;
    best to just use 0.34 * Signal syntax for example, which reverts to this class.
    use this for more complex amplitude functions
    
    use Gain() to change in dB
    """
    def __init__(self, *amps):
        self.amps = amps
    
    def realise(self, audio):
        # TODO do multiple channels at the same time?
        for (i,amp) in enumerate(self.amps):
            # TODO shouldn't this just affect a copy of audio????
            # above comment was previously for the line:
            # audio.audio = self.size*audio.audio
            if isnumber(amp):
                audio.audio[i,:] *= amp
            elif isinstance(amp, Curve):
                vals = amp.flatten(audio.sample_rate)
                # TODO view or copy?
                # TODO what if curve duration doesn't match signal?
                # or can we have curve duration extracted from signal? automatically matching it
                # should we just stretch the last value of curve?
                # should we define curve.conform?
                # also what if curve is too long?
                audio.audio[i,0:amp.num_samples(audio.sample_rate)] *= vals
                audio.audio[i,amp.num_samples(audio.sample_rate):] *= amp.endpoint()
            else:
                raise TypeError("Unsupported amplitude type")

class AmpFreq(Transform):
    """
    have the amplitude change according to a sine function over time continuously,
    with given width (size) and frequency
    TODO again the factors should be perhaps logarithimic
    """
    def __init__(self, frequency, size, phase=0):
        self.frequency = frequency
        self.size = size
        self.phase = phase
    
    def realise(self, audio):
        """ audio is Audio instance"""
        assert isinstance(audio, Audio) # TODO remove this after debug hopefully
        
        sin = np.sin(self.phase + self.frequency * \
                     np.linspace(0, audio.duration(), audio.length(), False) * 2 * np.pi)
        audio *= (sin * self.size + (1-self.size))
        # remember [:] is necessary to retain changes
        


class Limiter(Transform):
    """ Cuts any sample that exceed some amount.
    Amount can be an absolute value amplitude,
    or a ratio/percentage of the current maximum.
    
    minimum params are to limit from below in the range [-min,+min]
    which is just experimental
    """
    def __init__(self, max_amplitude=None, max_ratio=None, max_dB=None,
                       min_amplitude=None, min_ratio=None, min_dB=None):
        """ at most one max can to be non-None, at most one min as well"""
        assert (max_amplitude is not None) + (max_ratio is not None) + (max_dB is not None) <= 1
        assert (min_amplitude is not None) + (min_ratio is not None) + (min_dB is not None) <= 1
        
        #TODO more assertions
        
        if max_dB is not None or min_dB is not None:
            raise NotImplementedError
            # TODO
        
        self.is_min = not (min_amplitude is None and min_ratio is None and min_dB is None)        
        self.is_max = not (max_amplitude is None and max_ratio is None and max_dB is None)
        
        self.max_amplitude = max_amplitude
        self.max_ratio = max_ratio
        self.max_dB = max_dB
        self.min_amplitude = min_amplitude
        self.min_ratio = min_ratio
        self.min_dB = min_dB
    
    def realise(self, audio):
        # convert to the amplitude case then continue normally
        if self.is_max:
            if self.max_ratio is not None:
                self.max_amplitude = self.max_ratio*np.max(np.abs(audio.audio))
        
            # TODO do the same for dBs
            np.clip(audio.audio, -self.max_amplitude, self.max_amplitude, out=audio.audio)
        
        if self.is_min:
            if self.min_ratio is not None:
                self.min_amplitude = self.min_ratio*np.max(np.abs(audio.audio))
            #TODO same for dBs
            
            audio.audio[:,:] = np.sign(audio.audio) * \
                               np.clip(np.abs(audio.audio), a_min=self.min_amplitude, a_max=None)
        


###### PANNING STUFF

class Mono(Transform):
    """ transforms multi-channel audio to mono
    """
    def realise(self, audio):
        audio.audio = np.sum(audio.audio, axis=0, keepdims=True)

class Pan(Transform):
    """ applies arbitrary function to amplitudes of all channels
    """
    width = 200 # means hard left is -100, hard right is 100
    #eps = 0.001 # can use this to avoid np.log(0) warning; not necessary
    # i.e. np.log((x+hardR)/width) below
    
    # you can set Pan.panLaw once and for all; anytime before mixdown() js good
    panLaw = -6 # -3 seems appropriate for headphones
    
    # TODO faster computations
    pan_shape = lambda x: np.log(x/Pan.width + 0.5)*(-Pan.panLaw / np.log(2)) # +0.1 to prevent log(0)
    LdB = lambda x: Pan.pan_shape(-x)
    RdB = lambda x: Pan.pan_shape(x)
    defaultStereo = lambda x: (Pan.LdB(x), Pan.RdB(x))
    
    def __init__(self, pan, scheme=defaultStereo):
        """ pan is a number or curve, which will be fed into the
        underlying panning scheme.
        
        The underlying panning scheme is a number or Curve/MultiCurve in R -> R^n.
        n is interpreted as number of affected output channels,
        and the output values as gains.
        the domain R may be defined by the user whichever way they want.
        
        the default panning scheme maps numbers in [-100,100] into (-inf, 0]^2
        """
        self.pan = pan
        self.scheme = scheme
    
    def realise(self, audio):
        # or maybe we can string some monos together and apply same panning for all?
        assert audio.num_channels() == 1, "panning is from mono to multi"
        
        if isnumber(self.pan):
            dBs = self.scheme(self.pan)
        elif isinstance(self.pan, Curve):
            dBs = self.scheme(self.pan.flatten(audio.sample_rate))
        
        audio.from_mono(len(dBs))
        
        for (i, dB) in enumerate(dBs):
            audio.audio[i,:len(dB)] *= DB_to_Linear(dB)
            audio.audio[i,len(dB):] *= DB_to_Linear(self.scheme(self.pan.endpoint())[i])

class Repan(Transform):
    """ Allows switching between channels.
    """
    def __init__(self, *channels):
        """ channels is a permutation on the existing channels.
        i.e. (1,0) switches left and right.
        None means leave channel empty.
        """
        assert isinstance(channels, tuple)
        self.channels = channels
    
    def realise(self, audio):
        new_audio = np.zeros(audio.audio.shape, dtype=np.float64)
        for i, channel in enumerate(self.channels):
            if channel is None:
                continue
            new_audio[i,:] = audio.audio[channel,:]
            
        audio.audio[:,:] = new_audio[:,:]


####### FILTERS #########

class Downsample_rough(Transform):
    """ skips samples. can hear the effects of aliasing.
    suppose factor is 3, then this copies all 3k-th samples into
    the 3k+1-th, 3k+2-th places.
    phase is supposed to let us choose 3k+1, 3k+2 as the main one for example
    # can be interesting to put 4k on L and 4k+2 on R, see if there is stereo effect
    """
    
    def __init__(self, factor=2, phase=0):
        self.factor = factor
        self.phase = phase
        assert isinstance(phase, int) and 0 <= phase < factor
        #assert phase == 0, "not implemented"
        if phase != 0:
            raise NotImplementedError # TODO
    
    def realise(self, audio):
        l = audio.audio.shape[1] #- self.phase
        
        for i in range(1, self.factor):
            less = 0 != (l % self.factor) <= i
            audio.audio[:,i::self.factor] = audio.audio[:,0:l + (-self.factor if less else 0):self.factor]
            #audio.audio[:,i::self.factor] = audio.audio[:,self.phase:l + (-self.factor if less else 0):self.factor]


###### EXPERIMENTS ######

class Convolution(Transform):
    """ is this the right name?
    squaring the signal, or multiplying by its own reverse
    """
    
    def __init__(self, forward=True, add=0, is_both_ways=False):
        self.forward = forward
        self.add = add
        self.is_both_ways = is_both_ways
    
    def realise(self, audio):
        # TODO the add works both ways to keep the signal away from zero
        # but we can also omit the sign thing, basically making the signal
        # more positive in general, and sounding less strange
        other = audio.audio[:,::(1 if self.forward else -1)]
        if self.is_both_ways:
            audio.audio[:,:] *= (self.add*np.sign(other) + other)
        else:
            audio.audio[:,:] *= (self.add + other)

class ADSR(Transform):
    """ applied ADSR envelope to signal
    """
    # TODO what if attack+decay+release > signal.duration?
    def __init__(self, attack, decay, sustain, release, hold=0): #hold=None?
        self.attack = attack
        self.hold = hold
        self.decay = decay
        self.sustain = sustain
        self.release = release
        
    def realise(self, audio):
        env_start = Line(0, 1, self.attack) | Constant(1, self.hold)
        env_start |= Line(1, self.sustain, duration = self.decay)
        length_start = env_start.num_samples(audio.sample_rate)
        # or maybe as one envelope by extrpolating from audio.duration()?
        env_end = Line(self.sustain, 0, duration=self.release)
        length_end = env_end.num_samples(audio.sample_rate)
        
        audio.audio[:,:length_start] *= env_start.flatten(audio.sample_rate)
        audio.audio[:,length_start:-length_end] *= self.sustain
        audio.audio[:,-length_end:] *= env_end.flatten(audio.sample_rate)


















