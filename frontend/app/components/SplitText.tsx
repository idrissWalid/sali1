"use client";

import { useRef, useEffect, useState } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { useGSAP } from '@gsap/react';

gsap.registerPlugin(ScrollTrigger);

interface SplitTextProps {
  text: string;
  className?: string;
  delay?: number;
  duration?: number;
  ease?: string;
  splitType?: 'chars' | 'words' | 'lines' | 'words, chars';
  from?: gsap.TweenVars;
  to?: gsap.TweenVars;
  threshold?: number;
  rootMargin?: string;
  textAlign?: 'left' | 'center' | 'right' | 'justify' | 'initial' | 'inherit';
  tag?: 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6' | 'p' | 'span' | 'div';
  onLetterAnimationComplete?: () => void;
}

const SplitText = ({
  text = "",
  className = '',
  delay = 50,
  duration = 1.25,
  ease = 'power3.out',
  splitType = 'chars',
  from = { opacity: 0, y: 40 },
  to = { opacity: 1, y: 0 },
  threshold = 0.1,
  rootMargin = '-100px',
  textAlign = 'center',
  tag = 'p',
  onLetterAnimationComplete
}: SplitTextProps) => {
  const ref = useRef<HTMLParagraphElement | HTMLHeadingElement | HTMLSpanElement | HTMLDivElement | null>(null);
  const animationCompletedRef = useRef(false);
  const onCompleteRef = useRef(onLetterAnimationComplete);
  const [fontsLoaded, setFontsLoaded] = useState(() => {
    if (typeof document !== 'undefined') {
      return document.fonts.status === 'loaded';
    }
    return false;
  });

  // Keep callback ref updated
  useEffect(() => {
    onCompleteRef.current = onLetterAnimationComplete;
  }, [onLetterAnimationComplete]);

  // Reset completion state when text changes to allow re-triggering animations
  useEffect(() => {
    animationCompletedRef.current = false;
  }, [text]);

  useEffect(() => {
    if (typeof document !== 'undefined' && document.fonts.status !== 'loaded') {
      document.fonts.ready.then(() => {
        setFontsLoaded(true);
      });
    }
  }, []);

  useGSAP(
    () => {
      if (!ref.current || !text || !fontsLoaded) return;
      // Prevent re-animation if already completed
      if (animationCompletedRef.current) return;
      const el = ref.current;

      const startPct = (1 - threshold) * 100;
      const marginMatch = /^(-?\d+(?:\.\d+)?)(px|em|rem|%)?$/.exec(rootMargin);
      const marginValue = marginMatch ? parseFloat(marginMatch[1]) : 0;
      const marginUnit = marginMatch ? marginMatch[2] || 'px' : 'px';
      const sign =
        marginValue === 0
          ? ''
          : marginValue < 0
            ? `-=${Math.abs(marginValue)}${marginUnit}`
            : `+=${marginValue}${marginUnit}`;
      const start = `top ${startPct}%${sign}`;

      let targets: Element[] = [];
      if (splitType.includes('chars')) {
        targets = gsap.utils.toArray(el.querySelectorAll('.split-char'));
      } else if (splitType.includes('words')) {
        targets = gsap.utils.toArray(el.querySelectorAll('.split-word'));
      } else {
        targets = [el];
      }

      if (targets.length === 0) return;

      // Set initial state
      gsap.set(targets, { ...from });

      const tween = gsap.to(
        targets,
        {
          ...to,
          duration,
          ease,
          stagger: delay / 1000,
          scrollTrigger: {
            trigger: el,
            start,
            once: true,
            fastScrollEnd: true,
            anticipatePin: 0.4
          },
          onComplete: () => {
            animationCompletedRef.current = true;
            onCompleteRef.current?.();
          },
          willChange: 'transform, opacity',
          force3D: true
        }
      );

      return () => {
        ScrollTrigger.getAll().forEach(st => {
          if (st.trigger === el) st.kill();
        });
        tween.kill();
      };
    },
    {
      dependencies: [
        text,
        delay,
        duration,
        ease,
        splitType,
        JSON.stringify(from),
        JSON.stringify(to),
        threshold,
        rootMargin,
        fontsLoaded
      ],
      scope: ref
    }
  );

  const renderContent = () => {
    if (!text) return null;
    const words = text.split(' ');
    
    return words.map((word, wordIdx) => {
      const chars = word.split('');
      return (
        <span
          key={wordIdx}
          className="split-word"
          style={{ display: 'inline-block', whiteSpace: 'nowrap' }}
        >
          {chars.map((char, charIdx) => (
            <span
              key={charIdx}
              className="split-char"
              style={{ display: 'inline-block' }}
            >
              {char}
            </span>
          ))}
          {wordIdx < words.length - 1 && (
            <span className="split-space" style={{ display: 'inline-block' }}>
              &nbsp;
            </span>
          )}
        </span>
      );
    });
  };

  const Tag = tag || 'p';
  const style = {
    textAlign,
    overflow: 'hidden',
    display: 'inline-block',
    whiteSpace: 'normal' as const,
    wordWrap: 'break-word' as const,
    willChange: 'transform, opacity'
  };
  const classes = `split-parent ${className}`;

  return (
    <Tag ref={ref as React.Ref<HTMLParagraphElement>} style={style} className={classes}>
      {renderContent()}
    </Tag>
  );
};

export default SplitText;
