"use client";

import { cn } from "@/lib/utils";
import React, { useEffect, useRef } from "react";
import { createNoise3D } from "simplex-noise";
import { motion } from "framer-motion";

interface VortexProps {
    children?: React.ReactNode;
    className?: string;
    containerClassName?: string;
    particleCount?: number;
    rangeY?: number;
    baseHue?: number;
    baseSpeed?: number;
    rangeSpeed?: number;
    baseRadius?: number;
    rangeRadius?: number;
    backgroundColor?: string;
}

export const Vortex = (props: VortexProps) => {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    // --- Trading colour palette ---
    // baseHue 190 → cyan / teal core
    // rangeHue 80  → sweeps through cyan → blue → violet
    // High saturation, slightly dimmed lightness for the fintech feel
    const particleCount = props.particleCount ?? 600;
    const particlePropCount = 9;
    const particlePropsLength = particleCount * particlePropCount;
    const rangeY = props.rangeY ?? 200;
    const baseTTL = 60;
    const rangeTTL = 160;
    const baseSpeed = props.baseSpeed ?? 0.0;
    const rangeSpeed = props.rangeSpeed ?? 1.2;
    const baseRadius = props.baseRadius ?? 1;
    const rangeRadius = props.rangeRadius ?? 2;
    // Cyan-teal core hue with a wide sweep into violet/indigo — matches trading UI palette
    const baseHue = props.baseHue ?? 190;
    const rangeHue = 80;
    const noiseSteps = 3;
    const xOff = 0.00125;
    const yOff = 0.00125;
    const zOff = 0.0004;
    // Deep near-black backdrop — slightly blue-tinted (not pure black) so cyan particles pop
    const backgroundColor = props.backgroundColor ?? "#02070f";

    const tickRef = useRef(0);
    const noise3D = useRef(createNoise3D());
    const particlePropsRef = useRef(new Float32Array(particlePropsLength));
    const centerRef = useRef<[number, number]>([0, 0]);
    const rafRef = useRef<number | null>(null);

    const TAU = 2 * Math.PI;
    const rand = (n: number) => n * Math.random();
    const randRange = (n: number) => n - rand(2 * n);
    const fadeInOut = (t: number, m: number) => {
        const hm = 0.5 * m;
        return Math.abs(((t + hm) % m) - hm) / hm;
    };
    const lerp = (n1: number, n2: number, speed: number) =>
        (1 - speed) * n1 + speed * n2;

    const resize = (canvas: HTMLCanvasElement) => {
        const container = containerRef.current;
        if (!container) return;
        canvas.width = container.clientWidth;
        canvas.height = container.clientHeight;
        centerRef.current = [canvas.width * 0.5, canvas.height * 0.5];
    };

    const initParticle = (i: number, canvas: HTMLCanvasElement) => {
        const props = particlePropsRef.current;
        const x = rand(canvas.width);
        const y = centerRef.current[1] + randRange(rangeY);
        const vx = 0;
        const vy = 0;
        const life = 0;
        const ttl = baseTTL + rand(rangeTTL);
        const speed = baseSpeed + rand(rangeSpeed);
        const radius = baseRadius + rand(rangeRadius);
        const hue = baseHue + rand(rangeHue);
        props.set([x, y, vx, vy, life, ttl, speed, radius, hue], i);
    };

    const initParticles = (canvas: HTMLCanvasElement) => {
        tickRef.current = 0;
        particlePropsRef.current = new Float32Array(particlePropsLength);
        for (let i = 0; i < particlePropsLength; i += particlePropCount) {
            initParticle(i, canvas);
        }
    };

    const drawParticle = (
        x: number, y: number, x2: number, y2: number,
        life: number, ttl: number, radius: number, hue: number,
        ctx: CanvasRenderingContext2D
    ) => {
        ctx.save();
        ctx.lineCap = "round";
        ctx.lineWidth = radius;
        // Slightly lower lightness (52%) compared to default (60%) — less "rave", more "terminal"
        ctx.strokeStyle = `hsla(${hue},100%,52%,${fadeInOut(life, ttl)})`;
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        ctx.closePath();
        ctx.restore();
    };

    const checkBounds = (x: number, y: number, canvas: HTMLCanvasElement) =>
        x > canvas.width || x < 0 || y > canvas.height || y < 0;

    const updateParticle = (i: number, ctx: CanvasRenderingContext2D, canvas: HTMLCanvasElement) => {
        const p = particlePropsRef.current;
        const i2 = i + 1, i3 = i + 2, i4 = i + 3, i5 = i + 4, i6 = i + 5, i7 = i + 6, i8 = i + 7, i9 = i + 8;

        const x = p[i];
        const y = p[i2];
        const n = noise3D.current(x * xOff, y * yOff, tickRef.current * zOff) * noiseSteps * TAU;
        const vx = lerp(p[i3], Math.cos(n), 0.5);
        const vy = lerp(p[i4], Math.sin(n), 0.5);
        const life = p[i5];
        const ttl = p[i6];
        const speed = p[i7];
        const x2 = x + vx * speed;
        const y2 = y + vy * speed;
        const radius = p[i8];
        const hue = p[i9];

        drawParticle(x, y, x2, y2, life, ttl, radius, hue, ctx);

        p[i] = x2;
        p[i2] = y2;
        p[i3] = vx;
        p[i4] = vy;
        p[i5] = life + 1;

        if (checkBounds(x, y, canvas) || life > ttl) initParticle(i, canvas);
    };

    const renderGlow = (canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D) => {
        ctx.save();
        ctx.filter = "blur(8px) brightness(180%)";
        ctx.globalCompositeOperation = "lighter";
        ctx.drawImage(canvas, 0, 0);
        ctx.restore();

        ctx.save();
        ctx.filter = "blur(4px) brightness(150%)";
        ctx.globalCompositeOperation = "lighter";
        ctx.drawImage(canvas, 0, 0);
        ctx.restore();
    };

    const draw = (canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D) => {
        tickRef.current++;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = backgroundColor;
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        for (let i = 0; i < particlePropsLength; i += particlePropCount) {
            updateParticle(i, ctx, canvas);
        }

        renderGlow(canvas, ctx);

        ctx.save();
        ctx.globalCompositeOperation = "lighter";
        ctx.drawImage(canvas, 0, 0);
        ctx.restore();

        rafRef.current = window.requestAnimationFrame(() => draw(canvas, ctx));
    };

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;

        resize(canvas);
        initParticles(canvas);
        draw(canvas, ctx);

        const onResize = () => {
            resize(canvas);
        };
        window.addEventListener("resize", onResize);

        return () => {
            window.removeEventListener("resize", onResize);
            if (rafRef.current) cancelAnimationFrame(rafRef.current);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    return (
        <div className={cn("relative h-full w-full", props.containerClassName)}>
            <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 1.2 }}
                ref={containerRef}
                className="absolute inset-0 z-0 h-full w-full"
            >
                <canvas ref={canvasRef} className="block h-full w-full" />
            </motion.div>

            <div className={cn("relative z-10", props.className)}>
                {props.children}
            </div>
        </div>
    );
};
