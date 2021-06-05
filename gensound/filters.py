# -*- coding: utf-8 -*-
"""
Created on Wed Mar 25 15:42:08 2020

@author: Dror
"""

import numpy as np
from gensound.settings import _supported
from gensound.curve import Curve, Line, Logistic, Constant
from gensound.audio import Audio
from gensound.transforms import Transform
from gensound.utils import lambda_to_range, DB_to_Linear, \
                  isnumber, iscallable, \
                  num_samples, samples_slice

# TODO top-class FIR/IIR/Filter?
# that could include a useful function for debugging that generates the impulse response


######## FIRs


class Filter:
    # https://stackoverflow.com/a/37841802
    def plot_frequency_response(self, sample_rate):
        def H(z):
            b,a = self.coefficients(sample_rate)
            num = sum([z**(len(b) - i - 1)*b[i] for i in range(len(b))])
            denom = sum([z**(len(a) - i - 1)*a[i] for i in range(len(a))])
            return num/denom
    
        #import numpy as np
        import matplotlib.pyplot as plt
    
        w_range = np.linspace(0, np.pi, 1000)
        vals = np.abs(H(np.exp(1j*w_range)))
        #plt.xticks(w_range[::50]*sample_rate/2/np.pi)
        plt.xscale('log')
        plt.ylim(0, max(vals)*1.05)
        plt.plot(w_range*sample_rate/2/np.pi, vals)
        
        #plt.show()


class FIR(Transform):
    """ Implements a general-purpose FIR. Subclasses of this can deal solely with
    computing the desired coefficients by overriding FIR.coefficients,
    leaving the actual application to FIR.realise.
    The implementation here may change in the future, and is not guaranteed to be optimal.
    Possibly several alternative implementations will be included, for learning,
    testing and reference purposes. If more competitive implementation is required,
    it is easy enough to extend.
    """
    def __init__(self, *coefficients): # can override this if coefficients are independent of sample rate
        total = sum(coefficients)
        self.h = [c/total for c in coefficients]
        
    def coefficients(self, sample_rate): # override here if sample rate is needed
        # and just ignore the arguments for init
        return self.h
    
    def _parallel_copies(self, audio):
        """ Makes |h| copies of audio, shifting each by the proper amount
        and multiplying by the appropriate coefficient, then summing.
        """
        h = self.coefficients(audio.sample_rate)
        n = audio.length
        parallel = np.zeros((len(h), audio.num_channels, n+len(h)-1), dtype=np.float64)
        
        for i in range(len(h)):
            parallel[i,:,i:n+i] = h[i]*audio.audio
            
        audio.audio[:,:] = np.sum(parallel, axis=0)[:,:n] # TODO trims the end, how to handle this
    
    def _standing_sum(self, audio):
        """ Sums scaled copies of audio into a single ndarray.
        """
        h = self.coefficients(audio.sample_rate)
        new_audio = np.zeros_like((audio.num_channels, audio.length+len(h)-1))
        # could technically skip this first step
        
        for i in range(len(h)):
            new_audio[:,i:audio.length+i] += h[i]*audio.audio
        
        audio.audio[:,:] = new_audio[:,:audio.length] # trims the tail
    
    def realise(self, audio): # override if you have a particular implementation in mind
        self._parallel_copies(audio)
    
    # TODO maybe add class method to facilitate diagnosis of FIR, frequency/phase responses etc.

class MovingAverage(FIR):
    """ Averager Low Pass FIR, oblivious to sample rate.
    """
    def __init__(self, width):
        self.h = [1/width]*width
    



############ IIRs

class IIR(Transform, Filter):
    """ General-purpose IIR implementation. Subclasses can deal solely with coefficient selection,
    without worrying about the implementation. Override __init__ or coefficients,
    depending on whether or not the sample rate is relevant (typically is).
    """
    def __init__(self, feedforward, feedback): # override this if coefficients are independent of sample rate
        """ Expects two iterables. Feedback[0] is typically 1."""
        self.b = [c/feedback[0] for c in feedforward]
        self.a = [c/feedback[0] for c in feedback]
    
    def coefficients(self, sample_rate): # override this if sample rate is needed
        return (self.b, self.a)
    
    def realise(self, audio): # naive implementation
        # TODO at least the feed-forward coefficients can be computed en masse
        b, a = self.coefficients(audio.sample_rate)
        x = np.pad(audio.audio, ((0,0),(len(a)-1,0))) # max(len(a),len(b))-1
        y = np.zeros_like(x)
        
        for i in range(len(a), x.shape[1]):
            for n in range(len(b)):
                y[:,i] += b[n]*x[:,i-n]
                
            for m in range(1, len(a)):
                y[:,i] -= a[m]*y[:,i-m]
        
        audio.audio[:,:] = y[:,:audio.length]

class SimpleLPF(IIR):
    """
    McPherson
    """
    def __init__(self, cutoff):
        self.cutoff = cutoff
    
    def coefficients(self, sample_rate):
        Fc = 2*np.pi * self.cutoff / sample_rate
        
        # can also simplify instead of using beta
        beta = (1 - np.tan(Fc/2)) / (1 + np.tan(Fc/2))
        
        a = (1, -beta)
        b = ((1-beta)/2, (1-beta)/2)
        return (b, a)


class SimpleHPF(IIR):
    """
    McPherson
    """
    def __init__(self, cutoff):
        self.cutoff = cutoff
    
    def coefficients(self, sample_rate):
        Fc = 2*np.pi * self.cutoff / sample_rate
        
        beta = (1 - np.tan(Fc/2)) / (1 + np.tan(Fc/2))
        
        a = (1, -beta)
        b = ((1+beta)/2, -(1+beta)/2)
        return (b, a)



class SimpleLowShelf(IIR):
    """
    McPherson
    """
    def __init__(self, cutoff, gain):
        self.cutoff = cutoff
        self.gain = gain
    
    def coefficients(self, sample_rate):
        Fc = 2*np.pi * self.cutoff / sample_rate
        
        beta = (1 - np.tan(Fc/2)) / (1 + np.tan(Fc/2))
        
        a = (1, -beta)
        b = ((1 + self.gain + (1-self.gain)*beta)/2, -(1 - self.gain + (1+self.gain)*beta)/2)
        return (b, a)



class SimpleHighShelf(IIR):
    """
    McPherson
    """
    def __init__(self, cutoff, gain):
        self.cutoff = cutoff
        self.gain = gain
    
    def coefficients(self, sample_rate):
        Fc = 2*np.pi * self.cutoff / sample_rate
        
        beta = (1 - np.tan(Fc/2)) / (1 + np.tan(Fc/2))
        
        a = (1, -beta)
        b = ((1 + self.gain + (self.gain-1)*beta)/2, (1 - self.gain - (1+self.gain)*beta)/2)
        return (b, a)








