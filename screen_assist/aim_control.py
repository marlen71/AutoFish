"""Conservative, once-per-detection closed-loop controller. No OS input calls."""
import math
from .core import smooth_step


def stable_box(previous, current):
    if previous is None:
        return True
    pw,ph=previous.x2-previous.x1,previous.y2-previous.y1
    w,h=current.x2-current.x1,current.y2-current.y1
    if min(pw,ph,w,h)<=0:
        return False
    if max(w/pw,pw/w,h/ph,ph/h)>1.8:
        return False
    shift=math.dist(((previous.x1+previous.x2)/2,(previous.y1+previous.y2)/2),
                    ((current.x1+current.x2)/2,(current.y1+current.y2)/2))
    return shift<=max(12.,.65*math.hypot(pw,ph))


def safe_point(box, mode, head=.13, body=.42):
    if not all(math.isfinite(v) for v in (box.x1,box.y1,box.x2,box.y2,head,body)):
        return None
    if box.x2<=box.x1 or box.y2<=box.y1:
        return None
    ratio=head if mode=='head' else body
    # A malformed/extreme offset must never aim outside the confirmed box.
    ratio=max(.02,min(.98,ratio))
    return ((box.x1+box.x2)/2,box.y1+(box.y2-box.y1)*ratio)


class AimController:
    def __init__(self):
        self.reset()

    def reset(self):
        self.sequence=None
        self.target_id=None
        self.previous=None
        self.captured=None
        self.confirmed=0
        self.rx=self.ry=0.

    def step(self,sequence,captured,target_id,box,origin,point,now,smooth=10.,speed=900.,
             gain=.35,limit=4.,deadzone=2.,confirm_frames=2,max_age=.2):
        # Consume a result only once, including rejected/outlier frames.
        if sequence==self.sequence:
            return 0,0
        self.sequence=sequence
        if self.captured is not None and captured<=self.captured:
            return 0,0
        valid_point=(point is not None and all(math.isfinite(v) for v in (*point,*origin))
                     and box.x1<=point[0]<=box.x2 and box.y1<=point[1]<=box.y2)
        if not 0<=now-captured<=max_age or not valid_point:
            self.target_id=None
            self.confirmed=0
            self.rx=self.ry=0.
            return 0,0
        changed=target_id!=self.target_id
        stable=not changed and stable_box(self.previous,box)
        dt=min(max(captured-self.captured, .001),1/30) if self.captured is not None else 1/60
        self.confirmed=self.confirmed+1 if stable else 1
        self.target_id,self.previous,self.captured=target_id,box,captured
        if not stable:
            self.rx=self.ry=0.
        if self.confirmed<confirm_frames or not stable:
            return 0,0
        error=math.dist(origin,point)
        if error<=deadzone:
            self.rx=self.ry=0.
            return 0,0
        dx,dy=smooth_step(origin,point,smooth,dt,speed)
        dx,dy=dx*gain,dy*gain
        length=math.hypot(dx,dy)
        cap=min(limit,max(0.,error-deadzone))
        if length>cap and length:
            dx,dy=dx*cap/length,dy*cap/length
        dx,dy=dx+self.rx,dy+self.ry
        ix,iy=round(dx),round(dy)
        # Rounding/residuals cannot bypass the configured per-result step limit.
        while math.hypot(ix,iy)>limit:
            if abs(ix)>=abs(iy): ix-=1 if ix>0 else -1
            else: iy-=1 if iy>0 else -1
        self.rx,self.ry=dx-ix,dy-iy
        self.rx=max(-.5,min(.5,self.rx));self.ry=max(-.5,min(.5,self.ry))
        return ix,iy
