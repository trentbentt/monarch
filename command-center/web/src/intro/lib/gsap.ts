// Central GSAP module — import gsap and ScrollTrigger from here, never directly
// from "gsap" or "gsap/ScrollTrigger", to guarantee registration happens once.

import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

export { gsap, ScrollTrigger };
