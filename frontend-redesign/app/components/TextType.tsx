'use client';

import { useEffect, useRef, useState, useMemo, useCallback, ElementType, ReactNode } from 'react';
import { gsap } from 'gsap';
import './TextType.css';

interface TextTypeProps {
  text: string | string[];
  as?: ElementType;
  typingSpeed?: number;
  initialDelay?: number;
  pauseDuration?: number;
  deletingSpeed?: number;
  loop?: boolean;
  className?: string;
  showCursor?: boolean;
  hideCursorWhileTyping?: boolean;
  cursorCharacter?: ReactNode;
  cursorBlinkDuration?: number;
  cursorClassName?: string;
  textColors?: string[];
  variableSpeed?: { min: number; max: number };
  onSentenceComplete?: (sentence: string, index: number) => void;
  onComplete?: () => void;
  startOnVisible?: boolean;
  renderText?: (text: string) => ReactNode;
  [key: string]: unknown;
}

const TextType = ({
  text,
  as: Component = 'div',
  typingSpeed = 10,
  initialDelay = 0,
  pauseDuration = 2000,
  deletingSpeed = 30,
  loop = true,
  className = '',
  showCursor = true,
  hideCursorWhileTyping = false,
  cursorCharacter = '|',
  cursorClassName = '',
  cursorBlinkDuration = 0.5,
  textColors = [],
  variableSpeed,
  onSentenceComplete,
  onComplete,
  startOnVisible = false,
  reverseMode = false,
  renderText,
  ...props
}: TextTypeProps) => {
  const [displayedText, setDisplayedText] = useState('');
  const [currentCharIndex, setCurrentCharIndex] = useState(0);
  const [isDeleting, setIsDeleting] = useState(false);
  const [currentTextIndex, setCurrentTextIndex] = useState(0);
  const [isVisible, setIsVisible] = useState(!startOnVisible);
  const cursorRef = useRef<HTMLSpanElement>(null);
  const containerRef = useRef<HTMLElement>(null);
  const onSentenceCompleteRef = useRef(onSentenceComplete);
  const onCompleteRef = useRef(onComplete);

  // Mettre à jour les refs à chaque rendu
  useEffect(() => {
    onSentenceCompleteRef.current = onSentenceComplete;
    onCompleteRef.current = onComplete;
  }, [onSentenceComplete, onComplete]);

  const textArray = useMemo(() => (Array.isArray(text) ? text : [text]), [text]);

  const getRandomSpeed = useCallback(() => {
    if (!variableSpeed) return typingSpeed;
    const { min, max } = variableSpeed;
    return Math.random() * (max - min) + min;
  }, [variableSpeed, typingSpeed]);

  const getCurrentTextColor = () => {
    if (textColors.length === 0) return 'inherit';
    return textColors[currentTextIndex % textColors.length];
  };

  useEffect(() => {
    if (!startOnVisible || !containerRef.current) return;

    const observer = new IntersectionObserver(
      entries => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            setIsVisible(true);
          }
        });
      },
      { threshold: 0.1 }
    );

    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [startOnVisible]);

  useEffect(() => {
    if (showCursor && cursorRef.current) {
      gsap.set(cursorRef.current, { opacity: 1 });
      const animation = gsap.to(cursorRef.current, {
        opacity: 0,
        duration: cursorBlinkDuration,
        repeat: -1,
        yoyo: true,
        ease: 'power2.inOut'
      });
      return () => {
        animation.kill();
      };
    }
  }, [showCursor, cursorBlinkDuration]);

  // Si on passe en arrière-plan pendant l'écriture, on termine instantanément
  useEffect(() => {
    const handleVisibility = () => {
      if (document.hidden && textArray[currentTextIndex]) {
        setDisplayedText(textArray[currentTextIndex]);
        setCurrentCharIndex(textArray[currentTextIndex].length);
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => document.removeEventListener('visibilitychange', handleVisibility);
  }, [textArray, currentTextIndex]);

  useEffect(() => {
    if (!isVisible) return;

    let timeout: NodeJS.Timeout;
    const currentText = textArray[currentTextIndex];
    if (currentText === undefined || currentText === null) {
      return;
    }
    const processedText = reverseMode ? currentText.split('').reverse().join('') : currentText;

    const executeTypingAnimation = () => {
      if (document.hidden) {
        // Si la page est en arrière-plan, on termine l'animation immédiatement
        setDisplayedText(processedText);
        setCurrentCharIndex(processedText.length);
        return;
      }

      if (isDeleting) {
        if (displayedText === '') {
          setIsDeleting(false);
          if (currentTextIndex === textArray.length - 1 && !loop) {
            return;
          }

          if (onSentenceCompleteRef.current) {
            onSentenceCompleteRef.current(textArray[currentTextIndex], currentTextIndex);
          }

          setCurrentTextIndex(prev => (prev + 1) % textArray.length);
          setCurrentCharIndex(0);
          timeout = setTimeout(() => { }, pauseDuration);
        } else {
          timeout = setTimeout(() => {
            setDisplayedText(prev => prev.slice(0, -1));
          }, deletingSpeed);
        }
      } else {
        if (currentCharIndex < processedText.length) {
          timeout = setTimeout(
            () => {
              const chunkSize = 4; // Affiche 4 caractères à la fois pour un rendu beaucoup plus rapide
              setDisplayedText(prev => prev + processedText.slice(currentCharIndex, currentCharIndex + chunkSize));
              setCurrentCharIndex(prev => prev + chunkSize);
            },
            variableSpeed ? getRandomSpeed() : typingSpeed
          );
        } else if (textArray.length >= 1) {
          if (!loop && currentTextIndex === textArray.length - 1) {
            if (onSentenceCompleteRef.current) {
              onSentenceCompleteRef.current(textArray[currentTextIndex], currentTextIndex);
            }
            if (onCompleteRef.current) {
              onCompleteRef.current();
            }
            return;
          }
          timeout = setTimeout(() => {
            setIsDeleting(true);
          }, pauseDuration);
        }
      }
    };

    if (currentCharIndex === 0 && !isDeleting && displayedText === '') {
      timeout = setTimeout(executeTypingAnimation, initialDelay);
    } else {
      executeTypingAnimation();
    }

    return () => clearTimeout(timeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    currentCharIndex,
    displayedText,
    isDeleting,
    typingSpeed,
    deletingSpeed,
    pauseDuration,
    textArray,
    currentTextIndex,
    loop,
    initialDelay,
    isVisible,
    reverseMode,
    variableSpeed
  ]);

  const shouldHideCursor =
    hideCursorWhileTyping && (currentCharIndex < (textArray[currentTextIndex]?.length || 0) || isDeleting);

  const Element = Component as React.ElementType;
  return (
    <Element
      ref={containerRef as React.Ref<HTMLElement>}
      className={`text-type ${className}`}
      {...props}
    >
      <span className="text-type__content" style={{ color: getCurrentTextColor() || 'inherit' }}>
        {renderText ? renderText(displayedText) : displayedText}
      </span>
      {showCursor && (
        <span
          ref={cursorRef}
          className={`text-type__cursor ${cursorClassName} ${shouldHideCursor ? 'text-type__cursor--hidden' : ''}`}
        >
          {cursorCharacter}
        </span>
      )}
    </Element>
  );
};

export default TextType;
