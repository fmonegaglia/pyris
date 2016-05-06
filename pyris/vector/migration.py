from __future__ import division
import numpy as np
from scipy import interpolate
from ..misc import NaNs, Intersection, PolygonCentroid
from .. import HAS_MLPY, MLPYException, MLPYmsg
from .interpolation import InterpPCS
if HAS_MLPY: from .. import wave
import matplotlib.pyplot as plt


class AxisMigration( object ):

    '''
    MigRateBend - Read a List of River Planforms, Locate Individual Bends, compute Migration Rates
    '''

    omega0 = 6 # Morlet Wavelet Parameter
    icwtC = [] # Reconstructed ICWT Filtered Curvature
    
    def __init__( self, Xseries, Yseries, method='distance', use_wavelets=False ):
        '''Constructor - Get Planforms'''
        self.data = []
        self.method = method
        self.use_wavelets = use_wavelets
        for x, y in zip( Xseries, Yseries ):
            x, y = np.asarray(x), np.asarray(y)
            dx = np.ediff1d( x, to_begin=0 )
            dy = np.ediff1d( y, to_begin=0 )
            ds = np.sqrt( dx**2 + dy**2 )
            s = np.cumsum( ds )
            theta = np.arctan2( dy, dx )
            ntheta = theta.copy()
            for i in xrange( 1, theta.size ): # Set theta continuous
                if (theta[i]-theta[i-1])/np.pi > +1.9: theta[i] -=2*np.pi
                if (theta[i]-theta[i-1])/np.pi < -1.9: theta[i] +=2*np.pi
            c = -np.gradient( theta, np.gradient(s) )
            self.data.append( { 'x': x, 'y': y, 's': s, 'c':c } )
        return None

    def IterData( self ):
        '''Data Iterator'''
        for i, d in enumerate( self.data ): yield i, d

    def IterData2( self ):
        '''Data Pair Iterator'''
        for i, (d1, d2) in enumerate( zip( self.data[:-1], self.data[1:]) ): yield i, (d1, d2)

    def RevIterData2( self ):
        for i, (d1, d2) in enumerate( zip( self.data[:-1][::-1], self.data[1:][::-1] ) ): yield ( len(self.data)-2-i ), (d2, d1)

    def Iterbends( self, Idx ):
        '''Bend Iterator'''
        for i, (il,ir) in enumerate( zip( Idx[:-1], Idx[1:] ) ): yield i, (il, ir)

    def Iterbends2( self, Idx1, Idx2 ):
        '''Bend Pair Iterator'''
        for i, (i1l,i1r,i2l,i2r) in enumerate( zip( Idx1[:-1], Idx1[1:], Idx2[:-1], Idx2[1:] ) ): yield i, (i1l,i1r,i2l,i2r)

    def FindPeaks( self, arr ):
        '''Make NaN any element that is not a local maximum'''
        arr = np.abs( arr )
        arr[1:-1] = np.where(
            np.logical_and(arr[1:-1]>arr[2:], arr[1:-1]>arr[:-2]), arr[1:-1], np.nan
            )
        arr[0], arr[-1] = np.nan, np.nan
        return arr

    def FilterAll( self, reduction=0.33 ):
        '''Perform ICWT Filtering on all the Data'''
        for i, d in self.IterData():
            self.icwtC.append( self.FilterCWT( d['c'], d['s'], reduction=reduction ) )
        return None

    def FilterCWT( self, *args, **kwargs ):
        '''Use Inverse Wavelet Transform in order to Filter Data'''

        sgnl = args[0]
        time = args[1]
        reduction = kwargs.pop( 'reduction', 0.33 )
        full_output = kwargs.pop( 'full_output', False )

        if self.use_wavelets:
            if not HAS_MLPY:
                raise ImportError,\
                    'Package mlpy>=2.5.0 was not installed\n'\
                    'Run with "use_wavelets" set to False'
            N = sgnl.size
            dt = time[1] - time[0]
            omega0 = self.omega0
            scales = wave.autoscales( N=N, dt=dt, dj=0.1, wf='morlet', p=omega0 )
            cwt = wave.cwt( x=sgnl, dt=dt, scales=scales, wf='morlet', p=omega0 )
            gws = (np.abs(cwt)**2).sum( axis=1 ) / N
            peaks = np.full( gws.size, np.nan )
            peaks[1:-1] = np.where( np.logical_and(gws[1:-1]>gws[2:],gws[1:-1]>gws[:-2]), gws[1:-1], np.nan )
            for i in xrange( (~np.isnan(peaks)).astype(int).sum() ):
                p = np.nanargmax( peaks )
                peaks[p] = np.nan
                scalemax = scales[ p ] # Fundamental Harmonic
                mask = ( scales >= reduction*scalemax )
                icwt = wave.icwt( cwt[mask, :], dt, scales[mask], wf='morlet', p=omega0 )
                if not np.allclose(icwt, 0): break
        else:
            scales, scalemax = None, None
            icwt = sgnl
            for i in xrange( int(sgnl.size/10) ):
                sgnl[1:-1] = ( sgnl[:-2] + 2*sgnl[1:-1] + sgnl[2:] ) / 4
                sgnl[0] = ( 2*sgnl[0] + sgnl[1] ) / 3
                sgnl[-1] = ( 2*sgnl[-1] + sgnl[-2] ) / 3
        if full_output: return icwt, scales, scalemax
        return icwt
        
    def GetInflections( self, Cs ):
        '''Compute 0-crossings of channel curvature'''
        return np.where( Cs[1:]*Cs[:-1] < 0 )[0]

    def DistanceInflections( self, data, prev_data, prev_I ):
        '''Compute Inflection points by moving orthogonally from previous inflection points'''
        I = NaNs( prev_I.size )
        for j, prev_i in enumerate(prev_I):
            if np.isnan( prev_i ): continue
            i = self.FindOrthogonalPoint( data, prev_data, prev_i )
            if j > 0 and i <= I[j-1]: continue
            I[j] = i if i is not None else np.nan
        return np.asarray( I )            

    def GetAllInflections( self ):
        '''Get Inflection points on Inverse Wavelet Transform for Curvature.'''
        self.I = []
        if self.method == 'curvature':
            for i, d in self.IterData():
                self.I.append( self.GetInflections( self.icwtC[i] ) )
        elif self.method == 'distance':
            for i, d in self.IterData():
                if i == 0: self.I.append( self.GetInflections( self.icwtC[i] ) )
                else:
                    self.I.append( self.DistanceInflections( d, self.data[i-1], self.I[i-1] ) )
                    ## plt.figure()
                    ## plt.plot(self.data[i-1]['x'], self.data[i-1]['y'], 'k')
                    ## plt.plot(d['x'], d['y'], 'r')
                    ## for j in xrange(self.I[-1][np.isfinite(self.I[-1])].size):
                    ##     plt.plot( [self.data[i-1]['x'][self.I[i-1][np.isfinite(self.I[-1])][j]], self.data[i]['x'][self.I[i][np.isfinite(self.I[-1])][j]]],
                    ##               [self.data[i-1]['y'][self.I[i-1][np.isfinite(self.I[-1])][j]], self.data[i]['y'][self.I[i][np.isfinite(self.I[-1])][j]]],
                    ##               'go-' )
                    ## plt.axis('equal')
                    ## plt.show()
        return None

    def CorrelateInflections( self, *args, **kwargs ):
        '''Find the Closest Inflection Points'''

        self.CI1 = [] # Points on the Current Planform
        self.CI12 = [] # Points to which the First Planform Points Converge to the Second Planform
        self.CI11 = [] # Points where the second planform converges into itself to get in the next one (some bends become one bend)

        if self.method == 'distance':            
            self.CI1 = [ [] for _ in xrange( len( self.data ) ) ]
            self.CI12 = [ [] for _ in xrange( len( self.data ) ) ]
            for i, (d1, d2) in self.IterData2():
                mask = np.isfinite( self.I[i+1] )
                self.CI1[i+1] = self.I[i+1][ mask ].astype( int )
                self.CI1[i] = self.I[i][ mask ].astype( int )
                self.CI12[i] = self.CI1[i+1]
                
                ## x1, y1 = d1['x'], d1['y']
                ## x2, y2 = d2['x'], d2['y']
                ## plt.figure()
                ## plt.plot( x1, y1, 'b' )
                ## plt.plot( x2, y2, 'r' )
                ## plt.plot( x1[self.CI1[i]], y1[self.CI1[i]], 'bo' )
                ## plt.plot( x2[self.CI12[i]], y2[self.CI12[i]], 'ro' )
                ## for I in xrange(self.CI1[i].size):
                ##     plt.plot( [x1[self.CI1[i][I]], x2[self.CI12[i][I]]], [y1[self.CI1[i][I]], y2[self.CI12[i][I]]], 'g', lw=2 )
                ## for j in xrange( len(self.CI1[i]) ): plt.text( x1[self.CI1[i][j]], y1[self.CI1[i][j]], '%d' % self.CI1[i][j] )
                ## plt.axis('equal')
                ## plt.show()
            self.CI12[-1] = self.CI1[-1]
            return None

        elif self.method == 'curvature':
            C1 = self.I[0] # Initial Reference Planform
            # Go Forward
            for i, (d1, d2) in self.IterData2():
                self.CI11.append( C1 )
                C2 = self.I[i+1]
                C12 = np.zeros_like( C1, dtype=int )
                x1, y1 = d1['x'], d1['y']
                x2, y2 = d2['x'], d2['y']
                #Cs1 = self.icwtC[i]
                #Cs2 = self.icwtC[i+1]
                for ipoint, Ipoint in enumerate( C1 ):
                    xi1, yi1 = x1[Ipoint], y1[Ipoint]
                    xC2, yC2 = x2[C2], y2[C2] # Do not care about sign
                    #xC2 = np.where( Cs2[C2+1]*Cs1[Ipoint+1]<0, np.nan, x2[C2] ) # Take real curvature sign
                    #yC2 = np.where( Cs2[C2+1]*Cs1[Ipoint+1]<0, np.nan, y2[C2] ) # Take real curvature sign
                    # Find the Closest
                    C12[ipoint] = C2[ np.nanargmin( np.sqrt( (xC2-xi1)**2 + (yC2-yi1)**2 ) ) ]
                # There are some duplicated points - we need to get rid of them
                unique, counts = np.unique(C12, return_counts=True)
                duplic = unique[ counts>1 ]
                cduplic = counts[ counts > 1 ]
                for idup, (dup, cdup) in enumerate( zip( duplic, cduplic ) ):
                    idxs = np.where( C12==dup )[0]
                    idx = np.argmin( np.sqrt( (x2[dup]-x1[C1][idxs])**2 + (y2[dup]-y1[C1][idxs])**2 ) )
                    idxs = np.delete( idxs, idx )
                    C1 = np.delete( C1, idxs )
                    C12 = np.delete( C12, idxs )
    
                # Sometimes inflections are messed up. Sort them out!
                C1.sort()
                C12.sort()

            self.CI1.append(C1)
            self.CI12.append(C12)
            C1 = C12
        self.CI1.append(C12)
        return None

    def BendUpstreamDownstream( self, I, icwtC ):
        '''Bend Upstream-Downstream Indexes'''
        BUD = NaNs( icwtC.size )
        for i, (il,ir) in self.Iterbends( I ):
            iapex = il + np.abs( icwtC[ il:ir ] ).argmax()
            BUD[ il ] = 2 # Inflection Point
            BUD[ ir ] = 2 # Inflection Point
            BUD[ iapex ] = 0 # Bend Apex
            BUD[ il+1:iapex ] = -1  # Bend Upstream
            BUD[ iapex+1:ir ] = +1 # Bend Downstream
        return BUD

    def AllBUDs( self ):
        '''Bend Upstream-Downstream Indexes for All Planforms'''
        self.BUD = []
        for i, d in self.IterData():
            self.BUD.append( self.BendUpstreamDownstream( self.CI1[i], self.icwtC[i] ) )
        return None

    def GetBends( self, c ):
        '''Returns Inflection Points, Bend Indexes'''
        Idx = self.GetInflections( c )
        BIDX = self.LabelBends( c.size, Idx )
        return BIDX, Idx

    def LabelBends( self, *args, **kwargs ):
        'Bend label for each point of the planform'
        N = args[0] if isinstance( args[0], int ) else args[0].size
        Idx = args[1]
        labels = -np.ones( N, dtype=int )
        for i, (il, ir) in self.Iterbends( Idx ):
            labels[il:ir] = i
        return labels

    def LabelAllBends( self ):
        '''Apply Bend Labels to Each Planform'''
        self.BI = []
        for i, d in self.IterData():
            self.BI.append( self.LabelBends( d['s'].size, self.CI1[i] ) )
        return None

    def CorrelateBends( self ):
        '''Once Bends are Separated and Labeled, Correlate Them'''
        self.B12 = []
        for di, (d1, d2) in self.IterData2():
            B1 = self.BI[di]
            B2 = self.BI[di+1]
            B12 = -np.ones( B1.size, dtype=int )
            I1 = self.CI1[di]
            I2 = self.CI1[di+1]
            I12 = self.CI12[di]
            x1, y1 = d1['x'], d1['y']
            x2, y2 = d2['x'], d2['y']

            # X il momento tengo la correlazione tra gli inflections
            for i, (i1l, i1r, i2l, i2r) in self.Iterbends2( I1, I12 ):
                vals, cnts = np.unique( B2[i2l:i2r], return_counts=True )
                if len( vals ) == 0:
                    B12[i1l:i1r] = -1
                else:
                    B12[i1l:i1r] = vals[ cnts.argmax() ]

            # for DEBUG purposes
            ## for i, (il, ir) in self.Iterbends( I1 ):
            ##     b1 = slice(il,ir)
            ##     b2 = B2==B12[il]
            ##     if B12[il] < 0: continue
            ##     xb1, yb1 = x1[b1], y1[b1]
            ##     xb2, yb2 = x2[b2], y2[b2]
            ##     plt.figure()
            ##     plt.plot( x1, y1, 'k' )
            ##     plt.plot( x2, y2, 'r' )
            ##     plt.plot( xb1, yb1, 'k', lw=4 )
            ##     plt.plot( xb2, yb2, 'r', lw=4 )
            ##     plt.axis('equal')
            ##     plt.show()

            self.B12.append( B12 )
        self.B12.append( -np.ones( x2.size ) ) # Add a Convenience -1 Array for the Last Planform

        # for DEBUG purposes
        #B = 14
        #plt.figure()
        #for i, d in self.IterData():
        #    xi, yi = d['x'], d['y']
        #    if i == 0: plt.plot(xi, yi, 'k')
        #    X = xi[self.BI[i]==B]
        #    Y = yi[self.BI[i]==B]
        #    plt.plot(X, Y, lw=3)
        #    B = ( self.B12[i][ self.BI[i]==B ] )[0]
        #plt.show()

        return None        

    def FindOrthogonalPoint( self, data1, data2, i2, L=None ):
        '''Find the orthogonal point to second line on the first one'''
        [ x1, y1, s1 ] = data1['x'], data1['y'], data1['s']
        [ x2, y2, s2 ] = data2['x'], data2['y'], data2['s']
        if L is None: L = 10*np.gradient( s1 ).mean()
        a0 = np.arctan2( ( y2[i2+1] - y2[i2-1] ), ( x2[i2+1] - x2[i2-1] ) )
        a = a0 - np.pi/2 # Local Perpendicular Angle
        P = np.array( [ x2[i2], y2[i2] ] )
        R = np.array( [ np.cos(a), np.sin(a) ] ) * L
        hits = []
        for i in xrange( 1, x1.size ):
            Q = np.array( [ x1[i-1], y1[i-1] ] )
            S = np.array( [ x1[i], y1[i] ] ) - Q
            # Bound angle
            a1 = np.arctan2( (y1[i]-y1[i-1]), (x1[i]-x1[i-1]) )
            if ( a0 > +np.pi/2 and a1 < -np.pi/2 ): a1 += 2*np.pi
            if ( a0 < -np.pi/2 and a1 > +np.pi/2 ): a1 -= 2*np.pi
            if a1 > a0+np.pi/4 or a1 < a0-np.pi/4: continue

            segments_intersect, (xi, yi) = Intersection( P, Q, R, S )
            if segments_intersect: hits.append( np.sqrt( (x1-xi)**2 + (y1-yi)**2 ).argmin() )
        
        if hits == []: return None
        return np.min( hits )

    def MigrationRates( self, data1, data2, I1, I12, B1, B2, B12 ):
        '''Compute Local Migration Rates by connected individual bends'''

        [ x1, y1, s1 ] = data1['x'], data1['y'], data1['s']
        [ x2, y2, s2 ] = data2['x'], data2['y'], data2['s']
        [ dx, dy, dz]  = [ NaNs( x1.size ), NaNs( x1.size ), NaNs( x1.size ) ]

        for i, (il,ir) in self.Iterbends( I1 ):
            # Isolate Bend
            mask1 = np.full( s1.size, False, dtype=bool ); mask1[il:ir]=True
            mask2 = B2==B12[il]
            if B12[il] < 0: continue # Bend Is not Correlated
            bx1, by1, bs1, N1 = x1[mask1], y1[mask1], s1[mask1], mask1.sum() # Bend in First Planform
            bx2, by2, bs2, N2 = x2[mask2], y2[mask2], s2[mask2], mask2.sum() # Bend in Second Planform
            if N2 > N1: # Remove Random Points from Second Bend in order to interpolate
                idx = np.full( N2, True, bool )
                idx[ np.random.choice( np.arange(1,N2-1), N2-N1, replace=False ) ] = False
                bx2 = bx2[ idx ]
                by2 = by2[ idx ]
                N2 = bx2.size
            # ReInterpolate Second Planform (Parametric Cubic Spline)
            if N2 <= 3: kpcs=1 # If we have too few points, use linear interpolation
            else: kpcs=3
            bx2, by2 = InterpPCS( bx2, by2, N=N1, s=N2, k=kpcs, with_derivatives=False )
            # Compute Migration Rates for the whole bend
            dxb = bx2 - bx1
            dyb = by2 - by1
            dzb = np.sqrt( dxb**2 + dyb**2 )
            # Sinuosity Control
            sigma2 = ( bs2[-1] - bs2[0] ) / np.sqrt( (by2[-1]-by2[0])**2 + (bx2[-1]-bx2[0])**2 )
            sigma1 = ( bs1[-1] - bs1[0] ) / np.sqrt( (by1[-1]-by1[0])**2 + (bx1[-1]-bx1[0])**2 )
            # If Sinuosity has decreased significantly, assume a CutOff occurred
            if sigma1/sigma2 > 1.5: dxb, dyb, dzb = NaNs( N1 ), NaNs( N1 ), NaNs( N1 )
            # Set Migration Rate into Main Arrays
            dx[ mask1 ] = dxb
            dy[ mask1 ] = dyb
            dz[ mask1 ] = dzb

        return dx, dy, dz

    def AllMigrationRates( self, recall_on_cutoff=True ):
        '''Apply Migration Rates Algorithm to the whole set of planforms'''
        self.dx = []
        self.dy = []
        self.dz = []
        
        for i, (d1, d2) in self.IterData2():
            I1, I12 = self.CI1[i], self.CI12[i]
            B1, B2, B12 = self.BI[i], self.BI[i+1], self.B12[i]
            dxi, dyi, dzi = self.MigrationRates( d1, d2, I1, I12, B1, B2, B12 )
            self.dx.append( dxi ), self.dy.append( dyi ), self.dz.append( dzi )
        N = ( d2['s'] ).size
        self.dx.append( NaNs( N ) ), self.dy.append( NaNs( N ) ), self.dz.append( NaNs( N ) )
        return None

    def __call__( self, filter_reduction=0.33, return_on_cutoff=True ):
        self.FilterAll( reduction=filter_reduction )
        self.GetAllInflections()
        self.CorrelateInflections()
        self.LabelAllBends()
        self.AllBUDs()
        self.CorrelateBends()
        self.AllMigrationRates()
        return self.dx, self.dy, self.dz, self.icwtC, self.BI, self.B12, self.BUD

