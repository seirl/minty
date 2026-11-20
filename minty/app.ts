// Browser UI for 1.2L Ice Cream Recipes & Batch Wizard.
// Compiled by `minty` via esbuild (or Node's built-in stripTypeScriptTypes).

export interface IngredientMeta {
  id: string;
  name: string;
  g_per_tsp?: number | null;
  g_per_drop?: number | null;
}

export interface StepInput {
  item: string;
  name: string;
  grams: number;
  grams_fmt: string;
  hint: string;
  display: string;
  optional: boolean;
  note: string;
}

export type StepPhase = 'prep' | 'flavor' | 'chill' | 'churn' | 'mix_in' | 'pack';

export interface RecipeStep {
  phase: StepPhase;
  title: string;
  emoji: string;
  timer_sec: number | null;
  timer_label: string | null;
  inputs: StepInput[];
  inputs_inline: string;
  do: string;
}

export interface AggregatedIngredient {
  item: string;
  name: string;
  grams: number;
  grams_fmt: string;
  hint: string;
  display: string;
  parts: number[];
  optional: boolean;
  note: string;
}

export interface BaseRecipe {
  id: string;
  name: string;
  emoji: string;
  description: string;
  steps: RecipeStep[];
  ingredients: AggregatedIngredient[];
  yield_grams: number;
  yield_scales: Record<string, string>;
  used_by: string[];
}

export interface Recipe {
  id: string;
  name: string;
  emoji: string;
  category: string;
  reviewed: boolean;
  base: string | null;
  base_name: string | null;
  notes: string;
  own_steps: RecipeStep[];
  expanded_steps: RecipeStep[];
  ingredients: AggregatedIngredient[];
  total_grams: number;
  total_grams_fmt: string;
  optional_grams: number;
  optional_grams_fmt: string;
}

export interface CatalogPayload {
  reviewed_count: number;
  unreviewed_count: number;
  ingredients: Record<string, IngredientMeta>;
  bases: BaseRecipe[];
  recipes: Recipe[];
}

interface WizardStepItem {
  name: string;
  grams?: number;
  rawAmt?: string;
  item?: string;
  note?: string;
}

interface WizardStep {
  phase: string;
  title: string;
  items: WizardStepItem[];
  do: string;
  timerSec?: number | null;
  timerLabel?: string | null;
  isChill?: boolean;
  isChurn?: boolean;
}

type AppMode = 'book' | 'wizard';
type WizardScreen = 'pick' | 'checklist' | 'step';

type PrepUnit =
  | { type: 'merged'; base: BaseRecipe; members: Recipe[] }
  | { type: 'single'; recipe: Recipe };

interface WakeLockNavigator extends Navigator {
  wakeLock?: {
    request(type: 'screen'): Promise<unknown>;
  };
}

interface WebkitWindow extends Window {
  webkitAudioContext?: typeof AudioContext;
}

(() => {
  const dataEl = document.getElementById('minty-data');
  const DATA: CatalogPayload = JSON.parse(dataEl?.textContent ?? '{}') as CatalogPayload;
  const RECIPES: Recipe[] = DATA.recipes ?? [];
  const BASES_BY_ID: Record<string, BaseRecipe> = Object.fromEntries(
    (DATA.bases ?? []).map((b) => [b.id, b]),
  );
  const INGS: Record<string, IngredientMeta> = DATA.ingredients ?? {};

  let mode: AppMode = window.innerWidth < 780 ? 'wizard' : 'book';
  let activeItem: string = RECIPES[0]?.id ?? 'base:white-base';
  let scale = 1;
  let mobileReading = false;

  let selectedIds = new Set<string>(['mint-choc-chip', 'oreo-cookies', 'mango-sorbet']);
  let wizScreen: WizardScreen = 'pick';
  let wizSteps: WizardStep[] = [];
  let wizIdx = 0;
  const checkedSet = new Set<string>();

  let timerId: number | null = null;
  let timerRem = 0;
  let timerRunning = false;

  // ===========================================================================
  // DOM HELPERS & FORMATTING
  // ===========================================================================
  function byId<T extends HTMLElement = HTMLElement>(id: string): T {
    const el = document.getElementById(id);
    if (!el) throw new Error(`Missing element #${id}`);
    return el as T;
  }

  function fmtG(g: number): string {
    if (g >= 10) return `${Math.round(g)} g`;
    return `${Math.round(g * 100) / 100} g`;
  }

  function fmtTsp(t: number): string {
    if (t >= 3 && Math.abs(t / 3 - Math.round(t / 3)) < 0.08) {
      return `~${Math.round(t / 3)} tbsp`;
    }
    const e = Math.round(t * 8);
    if (e <= 0) return '';
    const w = Math.floor(e / 8);
    const r = e % 8;
    const fracMap: Record<number, string> = {
      1: '1/8',
      2: '1/4',
      3: '3/8',
      4: '1/2',
      5: '5/8',
      6: '3/4',
      7: '7/8',
    };
    const f = fracMap[r] ?? '';
    if (w && f) return `~${w} ${f} tsp`;
    if (w) return `~${w} tsp`;
    return `~${f} tsp`;
  }

  function fmtHint(itemId: string, grams: number): string {
    const meta = INGS[itemId];
    if (!meta) return '';
    if (meta.g_per_drop) {
      const d = Math.max(1, Math.round(grams / meta.g_per_drop));
      return `~${d} drop${d === 1 ? '' : 's'}`;
    }
    if (meta.g_per_tsp) {
      const tsp = grams / meta.g_per_tsp;
      if (tsp <= 3.2) return fmtTsp(tsp);
    }
    return '';
  }

  function fmtClock(sec: number): string {
    if (sec >= 3600 && sec % 3600 === 0) return `${sec / 3600} hr`;
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  }

  function esc(s: string | null | undefined): string {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ===========================================================================
  // THEME, TIMER & WAKE LOCK
  // ===========================================================================
  function syncThemeButton(): void {
    const isDark = document.documentElement.dataset.theme === 'dark';
    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.textContent = isDark ? '☀' : '☾';
      btn.title = isDark ? 'Switch to light mode' : 'Switch to dark mode';
    }
    const tc = document.getElementById('meta-theme-color');
    if (tc) {
      tc.setAttribute('content', isDark ? '#121214' : '#FFFFFF');
    }
  }

  function toggleTheme(): void {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem('minty-theme', next);
    } catch {
      // Storage unavailable
    }
    syncThemeButton();
  }

  async function requestWakeLock(): Promise<void> {
    const nav = navigator as WakeLockNavigator;
    if (nav.wakeLock) {
      try {
        await nav.wakeLock.request('screen');
      } catch {
        // Ignore in unsupported contexts
      }
    }
  }

  function beep(): void {
    try {
      const AudioCtor = window.AudioContext ?? (window as WebkitWindow).webkitAudioContext;
      if (!AudioCtor) return;
      const ctx = new AudioCtor();
      const notes: Array<[number, number, number]> = [
        [880, 0, 0.18],
        [1174.66, 0.2, 0.18],
        [1318.51, 0.4, 0.35],
      ];
      for (const [freq, start, dur] of notes) {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.frequency.setValueAtTime(freq, ctx.currentTime + start);
        gain.gain.setValueAtTime(0.2, ctx.currentTime + start);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + start + dur);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(ctx.currentTime + start);
        osc.stop(ctx.currentTime + start + dur);
      }
    } catch {
      // Audio unavailable
    }
  }

  function stopTimer(): void {
    if (timerId !== null) window.clearInterval(timerId);
    timerId = null;
    timerRunning = false;
  }

  function toggleTimer(sec: number, label: string): void {
    const btn = document.getElementById('timer-btn');
    if (!btn) return;
    if (timerRunning) {
      stopTimer();
      btn.classList.remove('running');
      btn.textContent = label;
      return;
    }
    timerRem = sec;
    timerRunning = true;
    btn.classList.add('running');
    btn.textContent = `${fmtClock(timerRem)} remaining — tap to reset`;
    timerId = window.setInterval(() => {
      timerRem--;
      if (timerRem <= 0) {
        stopTimer();
        beep();
        btn.classList.remove('running');
        btn.textContent = 'Done! Tap to restart';
      } else {
        btn.textContent = `${fmtClock(timerRem)} remaining — tap to reset`;
      }
    }, 1000);
  }

  // ===========================================================================
  // RECIPE BOOK VIEW
  // ===========================================================================
  function renderBaseSheet(b: BaseRecipe): string {
    const rows = b.ingredients
      .map((ing) => {
        const cells = [1, 2, 3, 4]
          .map((m) => {
            const g = ing.grams * m;
            const h = fmtHint(ing.item, g);
            return `<td class="num">${fmtG(g)}${h ? `<div class="ing-sub">${esc(h)}</div>` : ''}</td>`;
          })
          .join('');
        return `<tr><td>${esc(ing.name)}</td>${cells}</tr>`;
      })
      .join('');

    const totals = [1, 2, 3, 4]
      .map((m) => `<td class="num">${fmtG(b.yield_grams * m)}</td>`)
      .join('');

    const steps = b.steps
      .map((s, idx) => {
        const inline = s.inputs.map((i) => `${fmtG(i.grams)} ${i.name.toLowerCase()}`).join(', ');
        const meta = [inline, s.timer_label].filter(Boolean).join(' · ');
        return `
          <li class="step-row">
            <span class="step-idx">${idx + 1}</span>
            <div>
              <div class="step-head">
                <span class="step-title">${esc(s.title)}</span>
                ${meta ? `<span class="step-inline-meta"> — ${esc(meta)}</span>` : ''}
              </div>
              <p class="step-prose">${esc(s.do)}</p>
            </div>
          </li>
        `;
      })
      .join('');

    return `
      <div class="sheet-header">
        <div class="sheet-top-row">
          <h1 class="sheet-title">${esc(b.name)}</h1>
        </div>
        <div class="sheet-meta">${esc(b.description)} Weigh ${fmtG(b.yield_grams)} per tub when splitting.</div>
      </div>

      <h2 class="col-heading">Batch Multiplier Table</h2>
      <table class="ref-table" style="margin-bottom: 36px;">
        <thead>
          <tr>
            <th>Ingredient</th>
            <th>1× Tub</th>
            <th>2× Tubs</th>
            <th>3× Tubs</th>
            <th>4× Tubs</th>
          </tr>
        </thead>
        <tbody>
          ${rows}
          <tr class="total">
            <td>Total Base (${fmtG(b.yield_grams)} / tub)</td>
            ${totals}
          </tr>
        </tbody>
      </table>

      <h2 class="col-heading">Base Method</h2>
      <ol class="steps-ol">${steps}</ol>
    `;
  }

  function renderRecipeSheet(r: Recipe): string {
    const totalWeight = fmtG(r.total_grams * scale);
    const baseText = r.base === 'white-base' ? 'Master White Base' : (r.base_name ?? 'Standalone');

    const ingRows = r.ingredients
      .map((ing) => {
        const g = ing.grams * scale;
        const hint = fmtHint(ing.item, g);
        const split =
          ing.parts.length > 1
            ? `split ${ing.parts.map((p) => fmtG(p * scale)).join(' + ')}`
            : '';
        const details = [hint, split, ing.note, ing.optional ? 'optional' : '']
          .filter(Boolean)
          .join(' · ');
        return `
          <tr>
            <td class="ing-amt">${fmtG(g)}</td>
            <td class="ing-label">
              ${esc(ing.name)}
              ${details ? `<span class="ing-sub"> · ${esc(details)}</span>` : ''}
            </td>
          </tr>
        `;
      })
      .join('');

    const stepRows = r.expanded_steps
      .map((s, idx) => {
        const inSummary = s.inputs.map((i) => `${fmtG(i.grams * scale)} ${i.name}`).join(', ');
        const meta = [inSummary, s.timer_label].filter(Boolean).join(' · ');
        return `
          <li class="step-row">
            <span class="step-idx">${idx + 1}</span>
            <div>
              <div class="step-head">
                <span class="step-title">${esc(s.title)}</span>
                ${meta ? `<span class="step-inline-meta"> — ${esc(meta)}</span>` : ''}
              </div>
              <p class="step-prose">${esc(s.do)}</p>
            </div>
          </li>
        `;
      })
      .join('');

    const scaleButtons = [1, 2, 3]
      .map(
        (m) =>
          `<button class="scale-opt ${scale === m ? 'active' : ''}" data-action="set-scale" data-scale="${m}">${m}×</button>`,
      )
      .join('');

    return `
      <div class="sheet-header">
        <div class="sheet-top-row">
          <h1 class="sheet-title">
            ${r.emoji ? `${esc(r.emoji)} ` : ''}${esc(r.name)}
            ${!r.reviewed ? `<span class="tag-unreviewed">Unreviewed</span>` : ''}
          </h1>
          <div class="sheet-actions">
            <div class="scale-picker">${scaleButtons}</div>
            <button class="btn-start-batch" data-action="cook-single" data-id="${esc(r.id)}">Start batch →</button>
          </div>
        </div>
        <div class="sheet-meta">${esc(r.category)} · ${esc(baseText)} · ${totalWeight}</div>
        ${r.notes ? `<p class="sheet-note">${esc(r.notes)}</p>` : ''}
      </div>

      <div class="sheet-body">
        <div>
          <h2 class="col-heading">Ingredients</h2>
          <table class="ing-table">
            <tbody>${ingRows}</tbody>
          </table>
        </div>
        <div>
          <h2 class="col-heading">Method</h2>
          <ol class="steps-ol">${stepRows}</ol>
        </div>
      </div>
    `;
  }

  function renderBook(): void {
    const reviewed = RECIPES.filter((r) => r.reviewed);
    const unreviewed = RECIPES.filter((r) => !r.reviewed);

    byId('view-book').classList.toggle('mobile-reading', mobileReading);

    const renderLinks = (list: Recipe[], muted: boolean): string =>
      list
        .map(
          (r) => `
          <li>
              <button
              class="sidebar-btn ${muted ? 'muted-item' : ''} ${activeItem === r.id ? 'active' : ''}"
              data-action="open-item"
              data-id="${esc(r.id)}"
            >
              <span>${r.emoji ? `${esc(r.emoji)} ` : ''}${esc(r.name)}</span>
            </button>
          </li>
        `,
        )
        .join('');

    const baseLinks = DATA.bases
      .map(
        (b) => `
        <li>
          <button
            class="sidebar-btn ${activeItem === `base:${b.id}` ? 'active' : ''}"
            data-action="open-item"
            data-id="base:${esc(b.id)}"
          >
            <span>White Base (1×–4×)</span>
          </button>
        </li>
      `,
      )
      .join('');

    byId('sidebar').innerHTML = `
      <div class="sidebar-group">
        <h2 class="sidebar-heading">Reviewed (${reviewed.length})</h2>
        <ul class="sidebar-list">${renderLinks(reviewed, false)}</ul>
      </div>
      <div class="sidebar-group">
        <h2 class="sidebar-heading">Unreviewed (${unreviewed.length})</h2>
        <ul class="sidebar-list">${renderLinks(unreviewed, true)}</ul>
      </div>
      <div class="sidebar-group">
        <h2 class="sidebar-heading">Reference</h2>
        <ul class="sidebar-list">${baseLinks}</ul>
      </div>
    `;

    const container = byId('sheet-content');
    if (activeItem.startsWith('base:')) {
      const b = BASES_BY_ID[activeItem.slice(5)];
      container.innerHTML = b ? renderBaseSheet(b) : '';
    } else {
      const r = RECIPES.find((x) => x.id === activeItem) ?? RECIPES[0];
      container.innerHTML = r ? renderRecipeSheet(r) : '';
    }
  }

  // ===========================================================================
  // BATCH WIZARD COMPILER & RENDERER
  // ===========================================================================
  function compileWizardSteps(selected: Recipe[]): WizardStep[] {
    const steps: WizardStep[] = [];

    const baseCounts: Record<string, number> = {};
    for (const r of selected) {
      if (r.base) baseCounts[r.base] = (baseCounts[r.base] ?? 0) + 1;
    }

    const handledBases = new Set<string>();
    const units: PrepUnit[] = [];

    for (const r of selected) {
      if (r.base && (baseCounts[r.base] ?? 0) >= 2 && BASES_BY_ID[r.base]) {
        if (!handledBases.has(r.base)) {
          handledBases.add(r.base);
          const members = selected.filter((m) => m.base === r.base);
          units.push({
            type: 'merged',
            base: BASES_BY_ID[r.base],
            members,
          });
        }
      } else {
        units.push({ type: 'single', recipe: r });
      }
    }

    for (const u of units) {
      if (u.type === 'merged') {
        const N = u.members.length;
        const b = u.base;
        const names = u.members.map((m) => m.name).join(', ');

        b.steps.forEach((bs, idx) => {
          steps.push({
            phase: `Combined White Base (${N}×)`,
            title: idx === 0 ? `${bs.title} (${N}× in one bowl)` : `${bs.title} (${N}×)`,
            items: bs.inputs.map((i) => ({
              grams: i.grams * N,
              item: i.item,
              name: i.name,
              note: i.note,
            })),
            do: idx === 0 ? `Making ${names} together in one bowl. ${bs.do}` : bs.do,
            timerSec: bs.timer_sec,
            timerLabel: bs.timer_label ? `Start ${bs.timer_label} timer` : null,
          });
        });

        const splitG = Math.round(b.yield_grams);
        u.members.forEach((m, idx) => {
          const isLast = idx === N - 1;
          const flavorSteps = m.own_steps.filter((s) => s.phase === 'prep' || s.phase === 'flavor');
          const flavorInputs = flavorSteps.flatMap((s) => s.inputs);
          const flavorProse =
            flavorSteps.map((s) => s.do).join(' ') || 'Leave plain for pure sweet cream.';

          steps.push({
            phase: `Split Tub ${idx + 1} of ${N}`,
            title: `${m.name}: ${isLast ? 'Pour remaining base' : `Weigh ${splitG} g base`}`,
            items: [
              { rawAmt: isLast ? `~${splitG} g` : `${splitG} g`, name: b.name },
              ...flavorInputs.map((i) => ({
                grams: i.grams,
                item: i.item,
                name: i.name,
                note: i.note,
              })),
            ],
            do: `${
              isLast
                ? 'Pour the remaining base into your last tub.'
                : `Weigh ${splitG} g of white base into tub #${idx + 1}.`
            } ${flavorProse}`,
          });
        });
      } else {
        const r = u.recipe;
        const pre = r.expanded_steps.filter((s) => s.phase === 'prep' || s.phase === 'flavor');
        for (const s of pre) {
          steps.push({
            phase: r.name,
            title: `${r.name}: ${s.title}`,
            items: s.inputs.map((i) => ({
              grams: i.grams,
              item: i.item,
              name: i.name,
              note: i.note,
            })),
            do: s.do,
            timerSec: s.timer_sec,
            timerLabel: s.timer_label ? `Start ${s.timer_label} timer` : null,
          });
        }
      }
    }

    steps.push({
      phase: 'Chill',
      isChill: true,
      title: `Chill ${selected.length === 1 ? 'base' : `all ${selected.length} bases`} in the fridge`,
      items: [{ rawAmt: '2–4 hr', name: 'Refrigerate covered until cold' }],
      do: 'Chilling lets the guar gum hydrate completely. Tap Ready to Churn when you come back.',
      timerSec: 7200,
      timerLabel: 'Start 2 hr chill timer',
    });

    selected.forEach((r, idx) => {
      const post = r.own_steps.filter(
        (s) => s.phase === 'churn' || s.phase === 'mix_in' || s.phase === 'pack',
      );
      for (const s of post) {
        steps.push({
          phase: `Churn ${idx + 1} of ${selected.length} · ${r.name}`,
          isChurn: true,
          title: `${r.name}: ${s.title}`,
          items: s.inputs.map((i) => ({
            grams: i.grams,
            item: i.item,
            name: i.name,
            note: i.note,
          })),
          do: s.do,
          timerSec: s.timer_sec,
          timerLabel: s.timer_label ? `Start ${s.timer_label} timer` : null,
        });
      }
    });

    steps.push({
      phase: 'Done',
      title: 'All batches in the freezer',
      items: [],
      do: 'Let harden for 3–4 hours until firm and scoopable.',
    });

    return steps;
  }

  let pickListsMounted = false;

  function syncPickState(): void {
    const selected = RECIPES.filter((r) => selectedIds.has(r.id));
    const whiteCnt = selected.filter((r) => r.base === 'white-base').length;

    const noteEl = byId('wiz-merge-note');
    const whiteBase = BASES_BY_ID['white-base'];
    if (whiteCnt >= 2 && whiteBase) {
      noteEl.style.visibility = 'visible';
      noteEl.classList.remove('hidden');
      noteEl.textContent = `${whiteCnt}× White Base flavors selected — will mix ${fmtG(whiteBase.yield_grams * whiteCnt)} in 1 bowl (${fmtG(whiteBase.yield_grams)} per tub).`;
    } else {
      noteEl.style.visibility = 'hidden';
      noteEl.classList.remove('hidden');
      noteEl.textContent = '\u00A0';
    }

    document.querySelectorAll<HTMLElement>('#wiz-pick-lists [data-action="toggle-flavor"]').forEach((btn) => {
      const id = btn.dataset.id ?? '';
      btn.classList.toggle('selected', selectedIds.has(id));
    });

    const n = selectedIds.size;
    byId<HTMLButtonElement>('btn-start-wiz').disabled = n === 0;
    byId('btn-start-label').textContent =
      n === 0
        ? 'Select at least 1 flavor'
        : `Start prep (${n} ${n === 1 ? 'flavor' : 'flavors'})`;
    byId('wiz-clear-btn').textContent = n === 0 ? 'Reset default' : 'Clear';
  }

  function renderWizard(): void {
    const isPick = wizScreen === 'pick';
    const isCheck = wizScreen === 'checklist';
    const isStep = wizScreen === 'step';

    byId('wiz-pick').classList.toggle('hidden', !isPick);
    byId('wiz-checklist').classList.toggle('hidden', !isCheck);
    byId('wiz-step').classList.toggle('hidden', !isStep);
    byId('wiz-footer-pick').classList.toggle('hidden', !isPick);
    byId('wiz-footer-nav').classList.toggle('hidden', isPick);

    if (isPick) {
      if (!pickListsMounted) {
        const reviewed = RECIPES.filter((r) => r.reviewed);
        const unreviewed = RECIPES.filter((r) => !r.reviewed);
        const renderRows = (list: Recipe[]): string =>
          list
            .map(
              (r) => `
              <button class="pick-row" data-action="toggle-flavor" data-id="${esc(r.id)}">
                <div class="pick-left">
                  <span class="pick-box">✓</span>
                  <span class="pick-name">${r.emoji ? `${esc(r.emoji)} ` : ''}${esc(r.name)}</span>
                </div>
                <span class="pick-meta">${esc(r.base === 'white-base' ? 'White Base' : r.category)}</span>
              </button>
            `,
            )
            .join('');

        byId('wiz-pick-lists').innerHTML = `
          <div class="wiz-section-label">Reviewed</div>
          <div class="pick-list">${renderRows(reviewed)}</div>
          <div class="wiz-section-label">Unreviewed Drafts</div>
          <div class="pick-list">${renderRows(unreviewed)}</div>
        `;
        pickListsMounted = true;
      }
      syncPickState();
    } else if (isCheck) {
      const selected = RECIPES.filter((r) => selectedIds.has(r.id));
      byId('wiz-check-sub').textContent = `Total weights across ${selected
        .map((r) => r.name)
        .join(', ')}. Tap to check off.`;

      interface CheckRow {
        key: string;
        item: string;
        name: string;
        optional: boolean;
        grams: number;
      }
      const map = new Map<string, CheckRow>();
      for (const r of selected) {
        for (const ing of r.ingredients) {
          const k = `${ing.item}__${ing.optional ? 'opt' : 'req'}`;
          let row = map.get(k);
          if (!row) {
            row = { key: k, item: ing.item, name: ing.name, optional: ing.optional, grams: 0 };
            map.set(k, row);
          }
          row.grams += ing.grams;
        }
      }

      byId('wiz-check-rows').innerHTML = Array.from(map.values())
        .map((it) => {
          const done = checkedSet.has(it.key);
          const h = fmtHint(it.item, it.grams);
          return `
            <button class="check-item ${done ? 'done' : ''}" data-action="toggle-check" data-key="${esc(it.key)}">
              <span class="pick-box">✓</span>
              <span class="check-amt">${fmtG(it.grams)}</span>
              <span>
                ${esc(it.name)}
                ${h ? `<span class="ing-sub"> · ${esc(h)}</span>` : ''}
                ${it.optional ? `<span class="ing-sub"> · optional</span>` : ''}
              </span>
            </button>
          `;
        })
        .join('');

      byId('wiz-tools-note').textContent = `Containers needed: ${selected.length} freezer tub(s).`;
      byId('btn-next-label').textContent = 'Begin Step 1';
    } else if (isStep) {
      stopTimer();
      const s = wizSteps[wizIdx];
      if (!s) return;
      byId('wiz-step-meta').textContent = `Step ${wizIdx + 1} of ${wizSteps.length} · ${s.phase}`;

      const rows = s.items
        .map((it) => {
          const amt = it.rawAmt ?? fmtG(it.grams ?? 0);
          const h = it.item && it.grams !== undefined ? fmtHint(it.item, it.grams) : '';
          const sub = [h, it.note].filter(Boolean).join(' · ');
          return `
            <div class="tele-ing-row">
              <div>
                <div class="tele-ing-name">${esc(it.name)}</div>
                ${sub ? `<div class="ing-sub">${esc(sub)}</div>` : ''}
              </div>
              <div class="tele-ing-amt">${esc(amt)}</div>
            </div>
          `;
        })
        .join('');

      const timerHtml =
        s.timerSec && s.timerLabel
          ? `<button id="timer-btn" class="timer-button" data-action="toggle-timer" data-sec="${s.timerSec}" data-label="${esc(s.timerLabel)}">${esc(s.timerLabel)}</button>`
          : '';

      byId('wiz-step-body').innerHTML = `
        <h1 class="tele-step-title">${esc(s.title)}</h1>
        ${rows ? `<div class="tele-ing-list">${rows}</div>` : ''}
        <p class="tele-prose">${esc(s.do)}</p>
        ${timerHtml}
      `;

      const nextLbl = byId('btn-next-label');
      if (wizIdx === wizSteps.length - 1) nextLbl.textContent = 'Finish';
      else if (s.isChill) nextLbl.textContent = 'Ready to churn';
      else nextLbl.textContent = 'Next step';
    }
  }

  // ===========================================================================
  // ACTIONS & EVENT DELEGATION
  // ===========================================================================
  function setMode(m: AppMode): void {
    stopTimer();
    mode = m;
    byId('nav-book').classList.toggle('active', m === 'book');
    byId('nav-wizard').classList.toggle('active', m === 'wizard');
    byId('view-book').classList.toggle('hidden', m !== 'book');
    byId('view-wizard').classList.toggle('hidden', m !== 'wizard');
    byId('wiz-footer').classList.toggle('hidden', m !== 'wizard');

    if (m === 'book') renderBook();
    else renderWizard();
  }

  function startChecklist(): void {
    const selected = RECIPES.filter((r) => selectedIds.has(r.id));
    if (!selected.length) return;
    void requestWakeLock();
    wizSteps = compileWizardSteps(selected);
    wizIdx = 0;
    checkedSet.clear();
    wizScreen = 'checklist';
    renderWizard();
    window.scrollTo(0, 0);
  }

  function wizNext(): void {
    if (wizScreen === 'checklist') {
      wizScreen = 'step';
      wizIdx = 0;
    } else if (wizScreen === 'step') {
      if (wizIdx < wizSteps.length - 1) wizIdx++;
      else wizScreen = 'pick';
    }
    renderWizard();
    window.scrollTo(0, 0);
  }

  function wizPrev(): void {
    if (wizScreen === 'step') {
      if (wizIdx > 0) wizIdx--;
      else wizScreen = 'checklist';
    } else if (wizScreen === 'checklist') {
      wizScreen = 'pick';
    }
    renderWizard();
    window.scrollTo(0, 0);
  }

  function toggleJump(open: boolean): void {
    byId('jump-backdrop').classList.toggle('hidden', !open);
    byId('jump-sheet').classList.toggle('hidden', !open);
    if (open) {
      byId('jump-list').innerHTML = wizSteps
        .map(
          (s, idx) => `
          <button class="jump-row ${wizScreen === 'step' && idx === wizIdx ? 'current' : ''}" data-action="jump-step" data-idx="${idx}">
            <span>${idx + 1}. ${esc(s.title)}</span>
            <span class="ing-sub">${esc(s.phase)}</span>
          </button>
        `,
        )
        .join('');
    }
  }

  document.addEventListener('click', (e: MouseEvent) => {
    const target = (e.target as HTMLElement | null)?.closest<HTMLElement>('[data-action]');
    if (!target) return;
    const action = target.dataset.action;

    switch (action) {
      case 'go-home':
        if (mode === 'wizard') {
          wizScreen = 'pick';
          renderWizard();
        } else {
          mobileReading = false;
          renderBook();
        }
        break;
      case 'set-mode':
        setMode((target.dataset.mode as AppMode) ?? 'book');
        break;
      case 'print':
        if (mode !== 'book') setMode('book');
        window.print();
        break;
      case 'open-item':
        if (target.dataset.id) {
          activeItem = target.dataset.id;
          mobileReading = true;
          renderBook();
        }
        break;
      case 'close-mobile-sheet':
        mobileReading = false;
        renderBook();
        break;
      case 'set-scale':
        scale = Number(target.dataset.scale ?? 1);
        renderBook();
        break;
      case 'cook-single':
        if (target.dataset.id) {
          selectedIds = new Set([target.dataset.id]);
          setMode('wizard');
          startChecklist();
        }
        break;
      case 'clear-selection':
        if (selectedIds.size === 0) {
          selectedIds = new Set(['mint-choc-chip', 'oreo-cookies', 'mango-sorbet']);
        } else {
          selectedIds.clear();
        }
        syncPickState();
        break;
      case 'toggle-flavor':
        if (target.dataset.id) {
          if (selectedIds.has(target.dataset.id)) selectedIds.delete(target.dataset.id);
          else selectedIds.add(target.dataset.id);
          syncPickState();
        }
        break;
      case 'start-checklist':
        startChecklist();
        break;
      case 'jump-pick':
        wizScreen = 'pick';
        renderWizard();
        break;
      case 'toggle-check':
        if (target.dataset.key) {
          const isDone = !checkedSet.has(target.dataset.key);
          if (isDone) checkedSet.add(target.dataset.key);
          else checkedSet.delete(target.dataset.key);
          target.classList.toggle('done', isDone);
        }
        break;
      case 'toggle-timer':
        toggleTimer(Number(target.dataset.sec ?? 0), target.dataset.label ?? 'Start timer');
        break;
      case 'wiz-prev':
        wizPrev();
        break;
      case 'wiz-next':
        wizNext();
        break;
      case 'open-jump':
        toggleJump(true);
        break;
      case 'close-jump':
        toggleJump(false);
        break;
      case 'jump-step':
        wizScreen = 'step';
        wizIdx = Number(target.dataset.idx ?? 0);
        toggleJump(false);
        renderWizard();
        window.scrollTo(0, 0);
        break;
      case 'toggle-theme':
        toggleTheme();
        break;
      case 'jump-churn': {
        const idx = wizSteps.findIndex((s) => s.isChurn);
        if (idx !== -1) {
          wizScreen = 'step';
          wizIdx = idx;
          toggleJump(false);
          renderWizard();
          window.scrollTo(0, 0);
        }
        break;
      }
    }
  });

  window.addEventListener('keydown', (e: KeyboardEvent) => {
    if (mode !== 'wizard' || wizScreen === 'pick') return;
    if (e.key === 'ArrowRight') wizNext();
    if (e.key === 'ArrowLeft') wizPrev();
  });

  if ('serviceWorker' in navigator && /^https?:$/.test(window.location.protocol)) {
    window.addEventListener('load', () => {
      void navigator.serviceWorker.register('./sw.js');
    });
  }

  syncThemeButton();
  setMode(mode);
})();
