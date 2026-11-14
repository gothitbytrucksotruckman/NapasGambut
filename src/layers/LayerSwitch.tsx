// Layer switch (PRD 7.2): condition, HH, HV, coherence, radar picture. A radio group, so arrows move between options.
import { LAYERS, type Lang, type LayerId } from '../state/hash';
import { type Key, t } from '../i18n';
import './LayerSwitch.css';

export function LayerSwitch({
  layer,
  lang,
  onChange,
  hasCoherence = true,
}: {
  layer: LayerId;
  lang: Lang;
  onChange: (l: LayerId) => void;
  hasCoherence?: boolean;
}) {
  return (
    <fieldset className="layer-switch">
      <legend className="layer-switch__legend">{t(lang, 'layer.label')}</legend>
      <div className="layer-switch__opts">
        {LAYERS.map((l) => {
          const disabled = l === 'coh' && !hasCoherence;
          return (
            <label
              key={l}
              className={l === layer ? 'is-on' : disabled ? 'is-disabled' : undefined}
              title={disabled ? t(lang, 'pulse.noCoherence') : undefined}
            >
              <input
                type="radio"
                name="map-layer"
                value={l}
                checked={l === layer}
                disabled={disabled}
                onChange={() => {
                  if (!disabled) onChange(l);
                }}
              />
              {t(lang, `layer.${l}` as Key)}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
