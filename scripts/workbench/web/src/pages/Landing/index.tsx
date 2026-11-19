import { Link } from '@umijs/max';
import { useEffect } from 'react';
import type { ReactNode, SVGProps } from 'react';
import './index.css';

type IconProps = SVGProps<SVGSVGElement>;

function ArrowIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" {...props}>
      <path d="M4 10h11M11 5l5 5-5 5" />
    </svg>
  );
}

function SparkIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <path d="M12 2.5c.8 5.3 3.2 7.7 8.5 8.5-5.3.8-7.7 3.2-8.5 8.5C11.2 14.2 8.8 11.8 3.5 11c5.3-.8 7.7-3.2 8.5-8.5Z" />
      <path d="M19 2v4M21 4h-4" />
    </svg>
  );
}

function AuthorIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4.5 21c.6-4.5 3-6.8 7.5-6.8s6.9 2.3 7.5 6.8" />
    </svg>
  );
}

function SearchIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m15.5 15.5 5 5" />
    </svg>
  );
}

function ScanIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <path d="M8 3H4a1 1 0 0 0-1 1v4M16 3h4a1 1 0 0 1 1 1v4M21 16v4a1 1 0 0 1-1 1h-4M8 21H4a1 1 0 0 1-1-1v-4" />
      <path d="M7 12h10M12 7v10" />
    </svg>
  );
}

function ReportIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <path d="M6 3h9l3 3v15H6z" />
      <path d="M14 3v4h4M9 12h6M9 16h6" />
    </svg>
  );
}

function ShieldIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <path d="M12 2.5 20 6v5.5c0 5.2-3 8.5-8 10-5-1.5-8-4.8-8-10V6z" />
      <path d="m8.5 12 2.3 2.3 4.8-5" />
    </svg>
  );
}

function ClockIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.5 2" />
    </svg>
  );
}

const capabilityCards: Array<{
  index: string;
  icon: (props: IconProps) => ReactNode;
  eyebrow: string;
  title: string;
  description: string;
  tags: string[];
}> = [
  {
    index: '01',
    icon: AuthorIcon,
    eyebrow: 'AUTHOR INTELLIGENCE',
    title: '追踪作者的内容脉络',
    description:
      '从作者资料到历史帖子持续更新，把粉丝体量、内容表现与发布轨迹放进同一个可检索视图。',
    tags: ['作者主页', '帖子更新', '跨项目复用'],
  },
  {
    index: '02',
    icon: SearchIcon,
    eyebrow: 'TOPIC DISCOVERY',
    title: '扫描关键词与主题样本',
    description: '用关键词、作者或两者组合定义研究范围，让多个采集能力按实际可用性完成发现与补全。',
    tags: ['关键词搜索', '用户发现', '综合调研'],
  },
  {
    index: '03',
    icon: ScanIcon,
    eyebrow: 'VISUAL EVIDENCE',
    title: '读懂图片里的关键信息',
    description:
      '保存可用媒体，先用 OCR 提取画面文字，再按需补充图片理解，让视觉表达也进入证据链。',
    tags: ['本地媒体', 'OCR 识图', '图片理解'],
  },
  {
    index: '04',
    icon: ReportIcon,
    eyebrow: 'RESEARCH OUTPUT',
    title: '把样本沉淀成可复查结论',
    description: '用确定性数据摘要看清样本，再生成带上下文的研究报告；每一版结果都保留来源与边界。',
    tags: ['数据摘要', '大模型报告', '版本记录'],
  },
];

const workflowSteps = [
  {
    number: '01',
    title: '定义问题',
    copy: '选择作者、关键词或综合主题，明确要看的范围与样本量。',
  },
  {
    number: '02',
    title: '采集整理',
    copy: '系统把业务动作路由到可用能力，统一保存作者、帖子与项目关系。',
  },
  {
    number: '03',
    title: '补全证据',
    copy: '按需刷新详情、保存媒体、执行 OCR 或图片理解，标记真实完成状态。',
  },
  {
    number: '04',
    title: '形成结论',
    copy: '从可复现的数据摘要出发，再进入创作规律、机会与策略判断。',
  },
];

const researchModes = [
  {
    label: '看自己',
    title: '建立个人内容档案',
    copy: '持续维护自己的作者资料、帖子与报告，在同一个入口观察内容变化。',
    accent: 'coral',
    meta: 'PERSONAL ARCHIVE',
  },
  {
    label: '看作者',
    title: '拆解同行与标杆',
    copy: '把多个作者纳入项目，比较内容结构、互动表现和视觉表达。',
    accent: 'blue',
    meta: 'CREATOR BENCHMARK',
  },
  {
    label: '看主题',
    title: '验证一个内容方向',
    copy: '围绕关键词收集真实样本，识别高频表达、代表帖子与数据边界。',
    accent: 'lime',
    meta: 'TOPIC LANDSCAPE',
  },
];

function scrollToSection(id: string) {
  const section = document.getElementById(id);
  if (!section) return;

  const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  section.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
}

function LandingLogo() {
  return (
    <span className="landing-logo" role="img" aria-label="xhs-research">
      <span className="landing-logo-mark" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span className="landing-logo-type">
        <strong>xhs</strong>
        <span>/ research</span>
      </span>
    </span>
  );
}

function HeroWorkbenchPreview() {
  return (
    <div className="hero-preview" role="img" aria-label="从采集到研究报告的工作流示意">
      <div className="hero-preview-topbar">
        <span className="hero-preview-label">RESEARCH RUN</span>
        <span className="hero-preview-status">
          <span /> 进行中
        </span>
      </div>

      <div className="hero-preview-query">
        <span className="hero-preview-query-icon">
          <SearchIcon />
        </span>
        <div>
          <small>本次研究主题</small>
          <strong>AI 设计工具如何被讲清楚？</strong>
        </div>
        <span className="hero-preview-count">48 篇样本</span>
      </div>

      <div className="hero-preview-grid">
        <div className="hero-preview-sources">
          <div className="preview-section-title">
            <span>证据正在汇入</span>
            <small>3 / 4</small>
          </div>
          <div className="source-row is-complete">
            <span className="source-icon">
              <AuthorIcon />
            </span>
            <span>
              <strong>作者资料</strong>
              <small>6 位作者已整理</small>
            </span>
            <i>✓</i>
          </div>
          <div className="source-row is-complete">
            <span className="source-icon">
              <ReportIcon />
            </span>
            <span>
              <strong>帖子详情</strong>
              <small>标题 · 互动 · 媒体</small>
            </span>
            <i>✓</i>
          </div>
          <div className="source-row is-running">
            <span className="source-icon">
              <ScanIcon />
            </span>
            <span>
              <strong>画面文字</strong>
              <small>OCR 处理 32 / 48</small>
            </span>
            <i />
          </div>
        </div>

        <div className="hero-preview-insight">
          <div className="insight-note-label">FIELD NOTE / 07</div>
          <SparkIcon className="insight-spark" />
          <strong>把“功能”放进具体工作流，更容易形成高互动样本。</strong>
          <p>来自标题结构与画面文字的交叉观察</p>
          <div className="insight-bars" aria-hidden="true">
            <span style={{ '--bar-size': '84%' } as React.CSSProperties} />
            <span style={{ '--bar-size': '66%' } as React.CSSProperties} />
            <span style={{ '--bar-size': '45%' } as React.CSSProperties} />
          </div>
        </div>
      </div>

      <div className="hero-preview-footer">
        <span>采集</span>
        <i />
        <span>整理</span>
        <i />
        <span className="is-active">理解</span>
        <i />
        <span>报告</span>
      </div>
    </div>
  );
}

export default function LandingPage() {
  useEffect(() => {
    const workbenchTitle = document.title;
    document.title = 'xhs-research｜小红书内容研究工作台';

    return () => {
      document.title = workbenchTitle;
    };
  }, []);

  return (
    <div className="landing-page">
      <header className="landing-header">
        <div className="landing-container landing-header-inner">
          <Link to="/" className="landing-brand-link" aria-label="返回 xhs-research 官网首页">
            <LandingLogo />
          </Link>

          <nav className="landing-nav" aria-label="官网导航">
            <button type="button" onClick={() => scrollToSection('capabilities')}>
              能力
            </button>
            <button type="button" onClick={() => scrollToSection('workflow')}>
              流程
            </button>
            <button type="button" onClick={() => scrollToSection('scenarios')}>
              场景
            </button>
          </nav>

          <Link to="/my-projects" className="landing-header-cta">
            进入工作台
            <ArrowIcon />
          </Link>
        </div>
      </header>

      <main>
        <section className="landing-hero">
          <div className="landing-hero-grid landing-container">
            <div className="landing-hero-copy">
              <div className="landing-kicker">
                <span>小红书内容研究工作台</span>
                <i aria-hidden="true" />
                <span>LOCAL FIRST</span>
              </div>
              <h1>
                不止看见热门，
                <em>找到内容为什么有效。</em>
              </h1>
              <p>
                xhs-research
                把作者、关键词与主题调研装进一套可追踪的本地工作流：采集真实样本，补齐视觉证据，沉淀可复查的数据摘要与研究报告。
              </p>

              <div className="landing-hero-actions">
                <Link to="/my-projects" className="landing-button landing-button-primary">
                  开始研究
                  <ArrowIcon />
                </Link>
                <button
                  type="button"
                  className="landing-button landing-button-secondary"
                  onClick={() => scrollToSection('capabilities')}
                >
                  看看能做什么
                </button>
              </div>

              <ul className="landing-hero-proof" aria-label="产品特性">
                <li>
                  <ShieldIcon /> 数据保存在本地
                </li>
                <li>
                  <ClockIcon /> 长任务持续可追踪
                </li>
              </ul>
            </div>

            <div className="landing-hero-visual">
              <div className="hero-sticker hero-sticker-top" aria-hidden="true">
                可复查
              </div>
              <HeroWorkbenchPreview />
              <div className="hero-sticker hero-sticker-bottom" aria-hidden="true">
                不靠猜
              </div>
            </div>
          </div>

          <div className="landing-trust-strip">
            <div className="landing-trust-track">
              <span>真实样本</span>
              <i>✦</i>
              <span>全局主数据</span>
              <i>✦</i>
              <span>原子能力路由</span>
              <i>✦</i>
              <span>OCR 与图片理解</span>
              <i>✦</i>
              <span>可恢复后台任务</span>
              <i>✦</i>
              <span>版本化研究报告</span>
              <i>✦</i>
            </div>
          </div>
        </section>

        <section className="landing-section landing-capabilities" id="capabilities">
          <div className="landing-container">
            <div className="landing-section-heading">
              <div>
                <span className="landing-section-index">01 / 能力</span>
                <h2>把零散浏览，变成一条完整证据链。</h2>
              </div>
              <p>
                不为了一份报告临时拼凑数据。作者、帖子、媒体、任务和报告都在同一套系统里持续积累。
              </p>
            </div>

            <div className="capability-grid">
              {capabilityCards.map((card) => {
                const Icon = card.icon;
                return (
                  <article className="capability-card" key={card.index}>
                    <div className="capability-card-topline">
                      <span>{card.index}</span>
                      <span className="capability-icon">
                        <Icon />
                      </span>
                    </div>
                    <small>{card.eyebrow}</small>
                    <h3>{card.title}</h3>
                    <p>{card.description}</p>
                    <ul className="capability-tags" aria-label={`${card.title}包含的能力`}>
                      {card.tags.map((tag) => (
                        <li key={tag}>{tag}</li>
                      ))}
                    </ul>
                  </article>
                );
              })}
            </div>
          </div>
        </section>

        <section className="landing-section landing-workflow" id="workflow">
          <div className="landing-container">
            <div className="landing-section-heading landing-section-heading-light">
              <div>
                <span className="landing-section-index">02 / 流程</span>
                <h2>从一个问题出发，走到一份能继续行动的结论。</h2>
              </div>
              <p>
                每一步都有输入、状态和结果。离开页面，任务也会继续；需要登录或验证时，系统会停在可恢复的位置。
              </p>
            </div>

            <div className="workflow-grid">
              {workflowSteps.map((step, index) => (
                <article className="workflow-step" key={step.number}>
                  <div className="workflow-step-number">{step.number}</div>
                  <div className="workflow-step-marker">
                    <span />
                    {index < workflowSteps.length - 1 ? <i /> : null}
                  </div>
                  <h3>{step.title}</h3>
                  <p>{step.copy}</p>
                </article>
              ))}
            </div>

            <div className="workflow-stage">
              <div className="workflow-stage-sidebar">
                <span>LIVE TASK</span>
                <strong>研究任务 #042</strong>
                <p>每个阶段都留下可追踪的执行记录。</p>
              </div>
              <div className="workflow-stage-body">
                <div className="workflow-progress-head">
                  <span>主题研究 / AI 设计工具</span>
                  <strong>67%</strong>
                </div>
                <div className="workflow-progress-bar">
                  <span />
                </div>
                <div className="workflow-events">
                  <div className="is-done">
                    <i>✓</i>
                    <span>
                      <strong>关键词帖子已整理</strong>
                      <small>样本与作者关系已保存</small>
                    </span>
                    <time>14:28</time>
                  </div>
                  <div className="is-done">
                    <i>✓</i>
                    <span>
                      <strong>帖子详情已补全</strong>
                      <small>互动信息与媒体已更新</small>
                    </span>
                    <time>14:31</time>
                  </div>
                  <div className="is-active">
                    <i />
                    <span>
                      <strong>正在执行 OCR</strong>
                      <small>已完成 32 / 48 篇</small>
                    </span>
                    <time>现在</time>
                  </div>
                  <div>
                    <i />
                    <span>
                      <strong>生成研究摘要</strong>
                      <small>将在证据就绪后开始</small>
                    </span>
                    <time>等待</time>
                  </div>
                </div>
              </div>
              <aside className="workflow-stage-note">
                <span>为什么重要？</span>
                <p>
                  进度不是一个模糊的加载圈。你能看到系统做到哪一步、用了什么能力、哪里需要继续处理。
                </p>
              </aside>
            </div>
          </div>
        </section>

        <section className="landing-section landing-scenarios" id="scenarios">
          <div className="landing-container">
            <div className="landing-section-heading">
              <div>
                <span className="landing-section-index">03 / 场景</span>
                <h2>从一位创作者，到一个内容赛道。</h2>
              </div>
              <p>
                同一份主数据可以被不同项目复用。你可以从自己开始，也可以把研究范围逐步扩展到作者与主题。
              </p>
            </div>

            <div className="scenario-list">
              {researchModes.map((mode, index) => (
                <article className={`scenario-card scenario-card-${mode.accent}`} key={mode.label}>
                  <div className="scenario-card-index">0{index + 1}</div>
                  <div className="scenario-card-copy">
                    <span>{mode.label}</span>
                    <h3>{mode.title}</h3>
                    <p>{mode.copy}</p>
                  </div>
                  <div className="scenario-card-meta">{mode.meta}</div>
                  <ArrowIcon className="scenario-card-arrow" />
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="landing-principles">
          <div className="landing-container landing-principles-grid">
            <div className="principles-statement">
              <span className="landing-section-index">04 / 原则</span>
              <blockquote>
                “研究的价值，不在于生成更多文字，而在于知道每个判断来自哪里。”
              </blockquote>
            </div>
            <div className="principles-list">
              <article>
                <span>01</span>
                <div>
                  <h3>事实与判断分开</h3>
                  <p>数据摘要只做可复现的描述统计；策略与机会判断进入大模型报告。</p>
                </div>
              </article>
              <article>
                <span>02</span>
                <div>
                  <h3>数据关系不复制</h3>
                  <p>作者和帖子是全局主数据，项目只维护关系，更新一次即可在多个研究中复用。</p>
                </div>
              </article>
              <article>
                <span>03</span>
                <div>
                  <h3>能力失败可解释</h3>
                  <p>采集、OCR 与报告都进入统一任务生命周期，状态、警告与失败原因持续可见。</p>
                </div>
              </article>
            </div>
          </div>
        </section>

        <section className="landing-cta-section">
          <div className="landing-container landing-cta-panel">
            <div className="landing-cta-orbit" aria-hidden="true">
              <span>帖子</span>
              <span>作者</span>
              <span>媒体</span>
              <span>报告</span>
            </div>
            <div className="landing-cta-copy">
              <span>READY FOR YOUR NEXT QUESTION?</span>
              <h2>
                下一次刷到灵感时，
                <br />
                把它变成一个可以验证的问题。
              </h2>
              <p>从个人内容档案开始，或新建一个主题研究项目。</p>
              <Link to="/my-projects" className="landing-button landing-button-light">
                打开 xhs-research 工作台
                <ArrowIcon />
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="landing-footer">
        <div className="landing-container landing-footer-inner">
          <LandingLogo />
          <p>把内容研究留在自己的工作流里。</p>
          <Link to="/my-projects">
            进入工作台 <ArrowIcon />
          </Link>
        </div>
      </footer>
    </div>
  );
}
