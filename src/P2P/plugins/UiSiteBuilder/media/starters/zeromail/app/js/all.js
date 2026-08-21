

/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/lib/Base64Number.js ---- */


window.Base64Number = {
    _Rixits : "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz+/",
    fromNumber : function(number) {
        if (isNaN(Number(number)) || number === null ||
            number === Number.POSITIVE_INFINITY)
            throw "The input is not valid";
        if (number < 0)
            throw "Can't represent negative numbers now";

        var rixit; // like 'digit', only in some non-decimal radix
        var residual = Math.floor(number);
        var result = '';
        while (true) {
            rixit = residual % 64
            result = this._Rixits.charAt(rixit) + result;
            residual = Math.floor(residual / 64);
            if (residual == 0)
                break;
            }
        return result;
    },

    toNumber : function(rixits) {
        var result = 0;
        rixits = rixits.split('');
        for (var e = 0; e < rixits.length; e++) {
            result = (result * 64) + this._Rixits.indexOf(rixits[e]);
        }
        return result;
    }
};



/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/lib/Promise.coffee ---- */


(function() {
  var Promise,
    __slice = [].slice;

  Promise = (function() {
    Promise.when = function() {
      var args, num_uncompleted, promise, task, task_id, tasks, _fn, _i, _len;
      tasks = 1 <= arguments.length ? __slice.call(arguments, 0) : [];
      num_uncompleted = tasks.length;
      args = new Array(num_uncompleted);
      promise = new Promise();
      _fn = function(task_id) {
        return task.then(function() {
          args[task_id] = Array.prototype.slice.call(arguments);
          num_uncompleted--;
          if (num_uncompleted === 0) {
            return promise.complete.apply(promise, args);
          }
        });
      };
      for (task_id = _i = 0, _len = tasks.length; _i < _len; task_id = ++_i) {
        task = tasks[task_id];
        _fn(task_id);
      }
      return promise;
    };

    function Promise() {
      this.resolved = false;
      this.end_promise = null;
      this.result = null;
      this.callbacks = [];
    }

    Promise.prototype.resolve = function() {
      var back, callback, _i, _len, _ref;
      if (this.resolved) {
        return false;
      }
      this.resolved = true;
      this.data = arguments;
      if (!arguments.length) {
        this.data = [true];
      }
      this.result = this.data[0];
      _ref = this.callbacks;
      for (_i = 0, _len = _ref.length; _i < _len; _i++) {
        callback = _ref[_i];
        back = callback.apply(callback, this.data);
      }
      if (this.end_promise) {
        return this.end_promise.resolve(back);
      }
    };

    Promise.prototype.fail = function() {
      return this.resolve(false);
    };

    Promise.prototype.then = function(callback) {
      if (this.resolved === true) {
        callback.apply(callback, this.data);
        return;
      }
      this.callbacks.push(callback);
      return this.end_promise = new Promise();
    };

    return Promise;

  })();

  window.Promise = Promise;


  /*
  s = Date.now()
  log = (text) ->
  	console.log Date.now()-s, Array.prototype.slice.call(arguments).join(", ")
  
  log "Started"
  
  cmd = (query) ->
  	p = new Promise()
  	setTimeout ( ->
  		p.resolve query+" Result"
  	), 100
  	return p
  
  back = cmd("SELECT * FROM message").then (res) ->
  	log res
  	return "Return from query"
  .then (res) ->
  	log "Back then", res
  
  log "Query started", back
   */

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/lib/Property.coffee ---- */


(function() {
  Function.prototype.property = function(prop, desc) {
    return Object.defineProperty(this.prototype, prop, desc);
  };

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/lib/maquette.js ---- */


(function (global) {

  "use strict";


  // Utilities

  var emptyArray = [];

  var extend = function (base, overrides) {
    var result = {};
    Object.keys(base).forEach(function (key) {
      result[key] = base[key];
    });
    if(overrides) {
      Object.keys(overrides).forEach(function (key) {
        result[key] = overrides[key];
      });
    }
    return result;
  };

  // Hyperscript helper functions

  var appendChildren = function (parentSelector, insertions, main) {
    for(var i = 0; i < insertions.length; i++) {
      var item = insertions[i];
      if(Array.isArray(item)) {
        appendChildren(parentSelector, item, main);
      } else {
        if(item !== null && item !== undefined) {
          if(!item.hasOwnProperty("vnodeSelector")) {
            item = toTextVNode(item);
          }
          main.push(item);
        }
      }
    }
  };

  var toTextVNode = function (data) {
    return {
      vnodeSelector: "",
      properties: undefined,
      children: undefined,
      text: (data === null || data === undefined) ? "" : data.toString(),
      domNode: null
    };
  };

  // Render helper functions

  var missingTransition = function() {
    throw new Error("Provide a transitions object to the projectionOptions to do animations");
  };

  var defaultProjectionOptions = {
    namespace: undefined,
    eventHandlerInterceptor: undefined,
    styleApplyer: function(domNode, styleName, value) {
      // Provides a hook to add vendor prefixes for browsers that still need it.
      domNode.style[styleName] = value;
    },
    transitions: {
      enter: missingTransition,
      exit: missingTransition
    }
  };

  var applyDefaultProjectionOptions = function (projectionOptions) {
    return extend(defaultProjectionOptions, projectionOptions);
  };

  var setProperties = function (domNode, properties, projectionOptions) {
    if(!properties) {
      return;
    }
    var eventHandlerInterceptor = projectionOptions.eventHandlerInterceptor;
    for(var propName in properties) {
      var propValue = properties[propName];
      if(propName === "class" || propName === "className" || propName === "classList") {
        throw new Error("Property " + propName + " is not supported, use 'classes' instead.");
      } else if(propName === "classes") {
        // object with string keys and boolean values
        for(var className in propValue) {
          if(propValue[className]) {
            domNode.classList.add(className);
          }
        }
      } else if(propName === "styles") {
        // object with string keys and string (!) values
        for(var styleName in propValue) {
          var styleValue = propValue[styleName];
          if(styleValue) {
            if(typeof styleValue !== "string") {
              throw new Error("Style values may only be strings");
            }
            projectionOptions.styleApplyer(domNode, styleName, styleValue);
          }
        }
      } else if(propName === "key") {
        continue;
      } else if(propValue === null || propValue === undefined) {
        continue;
      } else {
        var type = typeof propValue;
        if(type === "function") {
          if(eventHandlerInterceptor && (propName.lastIndexOf("on", 0) === 0)) { // lastIndexOf(,0)===0 -> startsWith
            propValue = eventHandlerInterceptor(propName, propValue, domNode, properties); // intercept eventhandlers
            if(propName === "oninput") {
              (function () {
                // record the evt.target.value, because IE sometimes does a requestAnimationFrame between changing value and running oninput
                var oldPropValue = propValue;
                propValue = function (evt) {
                  evt.target["oninput-value"] = evt.target.value;
                  oldPropValue.apply(this, [evt]);
                };
              }());
            }
          }
          domNode[propName] = propValue;
        } else if(type === "string" && propName !== "value") {
          domNode.setAttribute(propName, propValue);
        } else {
          domNode[propName] = propValue;
        }
      }
    }
  };

  var updateProperties = function (domNode, previousProperties, properties, projectionOptions) {
    if(!properties) {
      return;
    }
    var propertiesUpdated = false;
    for(var propName in properties) {
      // assuming that properties will be nullified instead of missing is by design
      var propValue = properties[propName];
      var previousValue = previousProperties[propName];
      if(propName === "classes") {
        var classList = domNode.classList;
        for(var className in propValue) {
          var on = !!propValue[className];
          var previousOn = !!previousValue[className];
          if(on === previousOn) {
            continue;
          }
          propertiesUpdated = true;
          if(on) {
            classList.add(className);
          } else {
            classList.remove(className);
          }
        }
      } else if(propName === "styles") {
        for(var styleName in propValue) {
          var newStyleValue = propValue[styleName];
          var oldStyleValue = previousValue[styleName];
          if(newStyleValue === oldStyleValue) {
            continue;
          }
          propertiesUpdated = true;
          if(newStyleValue) {
            if(typeof newStyleValue !== "string") {
              throw new Error("Style values may only be strings");
            }
            projectionOptions.styleApplyer(domNode, styleName, newStyleValue);
          } else {
            projectionOptions.styleApplyer(domNode, styleName, "");
          }
        }
      } else {
        if(!propValue && typeof previousValue === "string") {
          propValue = "";
        }
        if(propName === "value") { // value can be manipulated by the user directly and using event.preventDefault() is not an option
          if(domNode[propName] !== propValue && domNode["oninput-value"] !== propValue) {
            domNode[propName] = propValue; // Reset the value, even if the virtual DOM did not change
            domNode["oninput-value"] = undefined;
          } // else do not update the domNode, otherwise the cursor position would be changed
          if(propValue !== previousValue) {
            propertiesUpdated = true;
          }
        } else if(propValue !== previousValue) {
          var type = typeof propValue;
          if(type === "function") {
            throw new Error("Functions may not be updated on subsequent renders (property: " + propName +
              "). Hint: declare event handler functions outside the render() function.");
          }
          if(type === "string") {
            domNode.setAttribute(propName, propValue);
          } else {
            if(domNode[propName] !== propValue) { // Comparison is here for side-effects in Edge with scrollLeft and scrollTop
              domNode[propName] = propValue;
            }
          }
          propertiesUpdated = true;
        }
      }
    }
    return propertiesUpdated;
  };

  var addChildren = function (domNode, children, projectionOptions) {
    if(!children) {
      return;
    }
    for(var i = 0; i < children.length; i++) {
      createDom(children[i], domNode, undefined, projectionOptions);
    }
  };

  var same = function (vnode1, vnode2) {
    if(vnode1.vnodeSelector !== vnode2.vnodeSelector) {
      return false;
    }
    if(vnode1.properties && vnode2.properties) {
      return vnode1.properties.key === vnode2.properties.key;
    }
    return !vnode1.properties && !vnode2.properties;
  };

  var findIndexOfChild = function (children, sameAs, start) {
    if(sameAs.vnodeSelector !== "") {
      // Never scan for text-nodes
      for(var i = start; i < children.length; i++) {
        if(same(children[i], sameAs)) {
          return i;
        }
      }
    }
    return -1;
  };

  var nodeAdded = function (vNode, transitions) {
    if(vNode.properties) {
      var enterAnimation = vNode.properties.enterAnimation;
      if(enterAnimation) {
        if(typeof enterAnimation === "function") {
          enterAnimation(vNode.domNode, vNode.properties);
        } else {
          transitions.enter(vNode.domNode, vNode.properties, enterAnimation);
        }
      }
    }
  };

  var nodeToRemove = function (vNode, transitions) {
    var domNode = vNode.domNode;
    if(vNode.properties) {
      var exitAnimation = vNode.properties.exitAnimation;
      if(exitAnimation) {
        domNode.style.pointerEvents = "none";
        var removeDomNode = function () {
          if(domNode.parentNode) {
            domNode.parentNode.removeChild(domNode);
          }
        };
        if(typeof exitAnimation === "function") {
          exitAnimation(domNode, removeDomNode, vNode.properties);
          return;
        } else {
          transitions.exit(vNode.domNode, vNode.properties, exitAnimation, removeDomNode);
          return;
        }
      }
    }
    if(domNode.parentNode) {
      domNode.parentNode.removeChild(domNode);
    }
  };

  var checkDistinguishable = function(childNodes, indexToCheck, parentVNode, operation) {
    var childNode = childNodes[indexToCheck];
    if (childNode.vnodeSelector === "") {
      return; // Text nodes need not be distinguishable
    }
    var key = childNode.properties ? childNode.properties.key : undefined;
    if (!key) { // A key is just assumed to be unique
      for (var i = 0; i < childNodes.length; i++) {
        if (i !== indexToCheck) {
          var node = childNodes[i];
          if (same(node, childNode)) {
            if (operation === "added") {
              throw new Error(parentVNode.vnodeSelector + " had a " + childNode.vnodeSelector + " child " +
                "added, but there is now more than one. You must add unique key properties to make them distinguishable.");
            } else {
              throw new Error(parentVNode.vnodeSelector + " had a " + childNode.vnodeSelector + " child " +
                "removed, but there were more than one. You must add unique key properties to make them distinguishable.");
            }
          }
        }
      }
    }
  };

  var updateChildren = function (vnode, domNode, oldChildren, newChildren, projectionOptions) {
    if(oldChildren === newChildren) {
      return false;
    }
    oldChildren = oldChildren || emptyArray;
    newChildren = newChildren || emptyArray;
    var oldChildrenLength = oldChildren.length;
    var newChildrenLength = newChildren.length;
    var transitions = projectionOptions.transitions;

    var oldIndex = 0;
    var newIndex = 0;
    var i;
    var textUpdated = false;
    while(newIndex < newChildrenLength) {
      var oldChild = (oldIndex < oldChildrenLength) ? oldChildren[oldIndex] : undefined;
      var newChild = newChildren[newIndex];
      if(oldChild !== undefined && same(oldChild, newChild)) {
        textUpdated = updateDom(oldChild, newChild, projectionOptions) || textUpdated;
        oldIndex++;
      } else {
        var findOldIndex = findIndexOfChild(oldChildren, newChild, oldIndex + 1);
        if(findOldIndex >= 0) {
          // Remove preceding missing children
          for(i = oldIndex; i < findOldIndex; i++) {
            nodeToRemove(oldChildren[i], transitions);
            checkDistinguishable(oldChildren, i, vnode, "removed");
          }
          textUpdated = updateDom(oldChildren[findOldIndex], newChild, projectionOptions) || textUpdated;
          oldIndex = findOldIndex + 1;
        } else {
          // New child
          createDom(newChild, domNode, (oldIndex < oldChildrenLength) ? oldChildren[oldIndex].domNode : undefined, projectionOptions);
          nodeAdded(newChild, transitions);
          checkDistinguishable(newChildren, newIndex, vnode, "added");
        }
      }
      newIndex++;
    }
    if(oldChildrenLength > oldIndex) {
      // Remove child fragments
      for(i = oldIndex; i < oldChildrenLength; i++) {
        nodeToRemove(oldChildren[i], transitions);
        checkDistinguishable(oldChildren, i, vnode, "removed");
      }
    }
    return textUpdated;
  };

  var createDom = function (vnode, parentNode, insertBefore, projectionOptions) {
    var domNode, i, c, start = 0, type, found;
    var vnodeSelector = vnode.vnodeSelector;
    if(vnodeSelector === "") {
      domNode = vnode.domNode = document.createTextNode(vnode.text);
      if(insertBefore !== undefined) {
        parentNode.insertBefore(domNode, insertBefore);
      } else {
        parentNode.appendChild(domNode);
      }
    } else {
      for (i = 0; i <= vnodeSelector.length; ++i) {
        c = vnodeSelector.charAt(i);
        if (i === vnodeSelector.length || c === '.' || c === '#') {
          type = vnodeSelector.charAt(start - 1);
          found = vnodeSelector.slice(start, i);
          if (type === ".") {
            domNode.classList.add(found);
          } else if (type === "#") {
            domNode.id = found;
          } else {
            if (found === "svg") {
              projectionOptions = extend(projectionOptions, { namespace: "http://www.w3.org/2000/svg" });
            }
            if (projectionOptions.namespace !== undefined) {
              domNode = vnode.domNode = document.createElementNS(projectionOptions.namespace, found);
            } else {
              domNode = vnode.domNode = document.createElement(found);
            }
            if (insertBefore !== undefined) {
              parentNode.insertBefore(domNode, insertBefore);
            } else {
              parentNode.appendChild(domNode);
            }
          }
          start = i + 1;
        }
      }
      initPropertiesAndChildren(domNode, vnode, projectionOptions);
    }
  };

  var initPropertiesAndChildren = function (domNode, vnode, projectionOptions) {
    addChildren(domNode, vnode.children, projectionOptions); // children before properties, needed for value property of <select>.
    if(vnode.text) {
      domNode.textContent = vnode.text;
    }
    setProperties(domNode, vnode.properties, projectionOptions);
    if(vnode.properties && vnode.properties.afterCreate) {
      vnode.properties.afterCreate(domNode, projectionOptions, vnode.vnodeSelector, vnode.properties, vnode.children);
    }
  };

  var updateDom = function (previous, vnode, projectionOptions) {
    var domNode = previous.domNode;
    if(!domNode) {
      throw new Error("previous node was not rendered");
    }
    var textUpdated = false;
    if(previous === vnode) {
      return textUpdated; // we assume that nothing has changed
    }
    var updated = false;
    if(vnode.vnodeSelector === "") {
      if(vnode.text !== previous.text) {
        domNode.nodeValue = vnode.text;
        textUpdated = true;
      }
    } else {
      if(vnode.vnodeSelector.lastIndexOf("svg", 0) === 0) { // lastIndexOf(needle,0)===0 means StartsWith
        projectionOptions = extend(projectionOptions, { namespace: "http://www.w3.org/2000/svg" });
      }
      if(previous.text !== vnode.text) {
        updated = true;
        if(vnode.text === undefined) {
          domNode.removeChild(domNode.firstChild); // the only textnode presumably
        } else {
          domNode.textContent = vnode.text;
        }
      }
      updated = updateChildren(vnode, domNode, previous.children, vnode.children, projectionOptions) || updated;
      updated = updateProperties(domNode, previous.properties, vnode.properties, projectionOptions) || updated;
      if(vnode.properties && vnode.properties.afterUpdate) {
        vnode.properties.afterUpdate(domNode, projectionOptions, vnode.vnodeSelector, vnode.properties, vnode.children);
      }
    }
    if(updated && vnode.properties && vnode.properties.updateAnimation) {
      vnode.properties.updateAnimation(domNode, vnode.properties, previous.properties);
    }
    vnode.domNode = previous.domNode;
    return textUpdated;
  };

  /**
   * Represents a {@link VNode} tree that has been rendered to a real DOM tree.
   * @interface Projection
   */
  var createProjection = function (vnode, projectionOptions) {
    if(!vnode.vnodeSelector) {
      throw new Error("Invalid vnode argument");
    }
    return {
      /**
       * Updates the projection with the new virtual DOM tree.
       * @param {VNode} updatedVnode - The updated virtual DOM tree. Note: The selector for the root of the tree must remain constant.
       * @memberof Projection#
       */
      update: function (updatedVnode) {
        if(vnode.vnodeSelector !== updatedVnode.vnodeSelector) {
          throw new Error("The selector for the root VNode may not be changed. (consider using dom.merge and add one extra level to the virtual DOM)");
        }
        updateDom(vnode, updatedVnode, projectionOptions);
        vnode = updatedVnode;
      },
      /**
       * The DOM node that is used as the root of this {@link Projection}.
       * @type {Element}
       * @memberof Projection#
       */
      domNode: vnode.domNode
    };
  };

  // Declaration of interfaces and callbacks, before the @exports maquette

  /**
   * A virtual representation of a DOM Node. Maquette assumes that {@link VNode} objects are never modified externally.
   * Instances of {@link VNode} can be created using {@link module:maquette.h}.
   * @interface VNode
   */

  /**
   * A CalculationCache object remembers the previous outcome of a calculation along with the inputs.
   * On subsequent calls the previous outcome is returned if the inputs are identical.
   * This object can be used to bypass both rendering and diffing of a virtual DOM subtree.
   * Instances of {@link CalculationCache} can be created using {@link module:maquette.createCache}.
   * @interface CalculationCache
   */

  /**
   * Keeps an array of result objects synchronized with an array of source objects.
   * Mapping provides a {@link Mapping#map} function that updates the {@link Mapping#results}.
   * The {@link Mapping#map} function can be called multiple times and the results will get created, removed and updated accordingly.
   * A {@link Mapping} can be used to keep an array of components (objects with a `renderMaquette` method) synchronized with an array of data.
   * Instances of {@link Mapping} can be created using {@link module:maquette.createMapping}.
   * @interface Mapping
   */

  /**
   * Used to create and update the DOM.
   * Use {@link Projector#append}, {@link Projector#merge}, {@link Projector#insertBefore} and {@link Projector#replace}
   * to create the DOM.
   * The `renderMaquetteFunction` callbacks will be called immediately to create the DOM. Afterwards, these functions
   * will be called again to update the DOM on the next animation-frame after:
   *
   *  - The {@link Projector#scheduleRender} function  was called
   *  - An event handler (like `onclick`) on a rendered {@link VNode} was called.
   *
   * The projector stops when {@link Projector#stop} is called or when an error is thrown during rendering.
   * It is possible to use `window.onerror` to handle these errors.
   * Instances of {@link Projector} can be created using {@link module:maquette.createProjector}.
   * @interface Projector
   */

  /**
   * @callback enterAnimationCallback
   * @param {Element} element - Element that was just added to the DOM.
   * @param {Object} properties - The properties object that was supplied to the {@link module:maquette.h} method
   */

  /**
   * @callback exitAnimationCallback
   * @param {Element} element - Element that ought to be removed from to the DOM.
   * @param {function(Element)} removeElement - Function that removes the element from the DOM.
   * This argument is supplied purely for convenience.
   * You may use this function to remove the element when the animation is done.
   * @param {Object} properties - The properties object that was supplied to the {@link module:maquette.h} method that rendered this {@link VNode} the previous time.
   */

  /**
   * @callback updateAnimationCallback
   * @param {Element} element - Element that was modified in the DOM.
   * @param {Object} properties - The last properties object that was supplied to the {@link module:maquette.h} method
   * @param {Object} previousProperties - The previous properties object that was supplied to the {@link module:maquette.h} method
   */

  /**
   * @callback afterCreateCallback
   * @param {Element} element - The element that was added to the DOM.
   * @param {Object} projectionOptions - The projection options that were used see {@link module:maquette.createProjector}.
   * @param {string} vnodeSelector - The selector passed to the {@link module:maquette.h} function.
   * @param {Object} properties - The properties passed to the {@link module:maquette.h} function.
   * @param {VNode[]} children - The children that were created.
   * @param {Object} properties - The last properties object that was supplied to the {@link module:maquette.h} method
   * @param {Object} previousProperties - The previous properties object that was supplied to the {@link module:maquette.h} method
   */

  /**
   * @callback afterUpdateCallback
   * @param {Element} element - The element that may have been updated in the DOM.
   * @param {Object} projectionOptions - The projection options that were used see {@link module:maquette.createProjector}.
   * @param {string} vnodeSelector - The selector passed to the {@link module:maquette.h} function.
   * @param {Object} properties - The properties passed to the {@link module:maquette.h} function.
   * @param {VNode[]} children - The children for this node.
   */

  /**
   * Contains simple low-level utility functions to manipulate the real DOM. The singleton instance is available under {@link module:maquette.dom}.
   * @interface MaquetteDom
   */

  /**
   * The main object in maquette is the maquette object.
   * It is either bound to `window.maquette` or it can be obtained using {@link http://browserify.org/|browserify} or {@link http://requirejs.org/|requirejs}.
   * @exports maquette
   */
  var maquette = {

    /**
     * The `h` method is used to create a virtual DOM node.
     * This function is largely inspired by the mercuryjs and mithril frameworks.
     * The `h` stands for (virtual) hyperscript.
     *
     * @param {string} selector - Contains the tagName, id and fixed css classnames in CSS selector format.
     * It is formatted as follows: `tagname.cssclass1.cssclass2#id`.
     * @param {Object} [properties] - An object literal containing properties that will be placed on the DOM node.
     * @param {function} properties.<b>*</b> - Properties with functions values like `onclick:handleClick` are registered as event handlers
     * @param {String} properties.<b>*</b> - Properties with string values, like `href:"/"` are used as attributes
     * @param {object} properties.<b>*</b> - All non-string values are put on the DOM node as properties
     * @param {Object} properties.key - Used to uniquely identify a DOM node among siblings.
     * A key is required when there are more children with the same selector and these children are added or removed dynamically.
     * @param {Object} properties.classes - An object literal like `{important:true}` which allows css classes, like `important` to be added and removed dynamically.
     * @param {Object} properties.styles - An object literal like `{height:"100px"}` which allows styles to be changed dynamically. All values must be strings.
     * @param {(string|enterAnimationCallback)} properties.enterAnimation - The animation to perform when this node is added to an already existing parent.
     * {@link http://maquettejs.org/docs/animations.html|More about animations}.
     * When this value is a string, you must pass a `projectionOptions.transitions` object when creating the projector {@link module:maquette.createProjector}.
     * @param {(string|exitAnimationCallback)} properties.exitAnimation - The animation to perform when this node is removed while its parent remains.
     * When this value is a string, you must pass a `projectionOptions.transitions` object when creating the projector {@link module:maquette.createProjector}.
     * {@link http://maquettejs.org/docs/animations.html|More about animations}.
     * @param {updateAnimationCallback} properties.updateAnimation - The animation to perform when the properties of this node change.
     * This also includes attributes, styles, css classes. This callback is also invoked when node contains only text and that text changes.
     * {@link http://maquettejs.org/docs/animations.html|More about animations}.
     * @param {afterCreateCallback} properties.afterCreate - Callback that is executed after this node is added to the DOM. Childnodes and properties have already been applied.
     * @param {afterUpdateCallback} properties.afterUpdate - Callback that is executed every time this node may have been updated. Childnodes and properties have already been updated.
     * @param {Object[]} [children] - An array of virtual DOM nodes to add as child nodes.
     * This array may contain nested arrays, `null` or `undefined` values.
     * Nested arrays are flattened, `null` and `undefined` will be skipped.
     *
     * @returns {VNode} A VNode object, used to render a real DOM later. NOTE: There are {@link http://maquettejs.org/docs/rules.html|three basic rules} you should be aware of when updating the virtual DOM.
     */
    h: function (selector, properties, childrenArgs) {
      if (typeof selector !== "string") {
        throw new Error();
      }
      var childIndex = 1;
      if (properties && !properties.hasOwnProperty("vnodeSelector") && !Array.isArray(properties) && typeof properties === "object") {
        childIndex = 2;
      } else {
        // Optional properties argument was omitted
        properties = undefined;
      }
      var text = undefined;
      var children = undefined;
      var argsLength = arguments.length;
      // Recognize a common special case where there is only a single text node
      if(argsLength === childIndex + 1) {
        var onlyChild = arguments[childIndex];
        if (typeof onlyChild === "string") {
          text = onlyChild;
        } else if (onlyChild !== undefined && onlyChild.length === 1 && typeof onlyChild[0] === "string") {
          text = onlyChild[0];
        }
      }
      if (text === undefined) {
        children = [];
        for (;childIndex<arguments.length;childIndex++) {
          var child = arguments[childIndex];
          if(child === null || child === undefined) {
            continue;
          } else if(Array.isArray(child)) {
            appendChildren(selector, child, children);
          } else if(child.hasOwnProperty("vnodeSelector")) {
            children.push(child);
          } else {
            children.push(toTextVNode(child));
          }
        }
      }
      return {
        /**
         * The CSS selector containing tagname, css classnames and id. An empty string is used to denote a text node.
         * @memberof VNode#
         */
        vnodeSelector: selector,
        /**
         * Object containing attributes, properties, event handlers and more @see module:maquette.h
         * @memberof VNode#
         */
        properties: properties,
        /**
         * Array of VNodes to be used as children. This array is already flattened.
         * @memberof VNode#
         */
        children: children,
        /**
         * Used in a special case when a VNode only has one childnode which is a textnode. Only used in combination with children === undefined.
         * @memberof VNode#
         */
        text: text,
        /**
         * Used by maquette to store the domNode that was produced from this {@link VNode}.
         * @memberof VNode#
         */
        domNode: null
      };
    },

    /**
     * @type MaquetteDom
     */
    dom: {
      /**
       * Creates a real DOM tree from a {@link VNode}. The {@link Projection} object returned will contain the resulting DOM Node under the {@link Projection#domNode} property.
       * This is a low-level method. Users wil typically use a {@link Projector} instead.
       * @memberof MaquetteDom#
       * @param {VNode} vnode - The root of the virtual DOM tree that was created using the {@link module:maquette.h} function. NOTE: {@link VNode} objects may only be rendered once.
       * @param {Object} projectionOptions - Options to be used to create and update the projection, see {@link module:maquette.createProjector}.
       * @returns {Projection} The {@link Projection} which contains the DOM Node that was created.
       */
      create: function (vnode, projectionOptions) {
        projectionOptions = applyDefaultProjectionOptions(projectionOptions);
        createDom(vnode, document.createElement("div"), undefined, projectionOptions);
        return createProjection(vnode, projectionOptions);
      },

      /**
       * Appends a new childnode to the DOM which is generated from a {@link VNode}.
       * This is a low-level method. Users wil typically use a {@link Projector} instead.
       * @memberof MaquetteDom#
       * @param {Element} parentNode - The parent node for the new childNode.
       * @param {VNode} vnode - The root of the virtual DOM tree that was created using the {@link module:maquette.h} function. NOTE: {@link VNode} objects may only be rendered once.
       * @param {Object} projectionOptions - Options to be used to create and update the projection, see {@link module:maquette.createProjector}.
       * @returns {Projection} The {@link Projection} that was created.
       */
      append: function (parentNode, vnode, projectionOptions) {
        projectionOptions = applyDefaultProjectionOptions(projectionOptions);
        createDom(vnode, parentNode, undefined, projectionOptions);
        return createProjection(vnode, projectionOptions);
      },

      /**
       * Inserts a new DOM node which is generated from a {@link VNode}.
       * This is a low-level method. Users wil typically use a {@link Projector} instead.
       * @memberof MaquetteDom#
       * @param {Element} beforeNode - The node that the DOM Node is inserted before.
       * @param {VNode} vnode - The root of the virtual DOM tree that was created using the {@link module:maquette.h} function. NOTE: {@link VNode} objects may only be rendered once.
       * @param {Object} projectionOptions - Options to be used to create and update the projection, see {@link module:maquette.createProjector}.
       * @returns {Projection} The {@link Projection} that was created.
       */
      insertBefore: function(beforeNode, vnode, projectionOptions) {
        projectionOptions = applyDefaultProjectionOptions(projectionOptions);
        createDom(vnode, beforeNode.parentNode, beforeNode, projectionOptions);
        return createProjection(vnode, projectionOptions);
      },

      /**
       * Merges a new DOM node which is generated from a {@link VNode} with an existing DOM Node.
       * This means that the virtual DOM and real DOM have one overlapping element.
       * Therefore the selector for the root {@link VNode} will be ignored, but its properties and children will be applied to the Element provided
       * This is a low-level method. Users wil typically use a {@link Projector} instead.
       * @memberof MaquetteDom#
       * @param {Element} domNode - The existing element to adopt as the root of the new virtual DOM. Existing attributes and childnodes are preserved.
       * @param {VNode} vnode - The root of the virtual DOM tree that was created using the {@link module:maquette.h} function. NOTE: {@link VNode} objects may only be rendered once.
       * @param {Object} projectionOptions - Options to be used to create and update the projection, see {@link module:maquette.createProjector}.
       * @returns {Projection} The {@link Projection} that was created.
       */
      merge: function (element, vnode, options) {
        options = applyDefaultProjectionOptions(options);
        vnode.domNode = element;
        initPropertiesAndChildren(element, vnode, options);
        return createProjection(vnode, options);
      }
    },

    /**
     * Creates a {@link CalculationCache} object, useful for caching {@link VNode} trees.
     * In practice, caching of {@link VNode} trees is not needed, because achieving 60 frames per second is almost never a problem.
     * @returns {CalculationCache}
     */
    createCache: function () {
      var cachedInputs = undefined;
      var cachedOutcome = undefined;
      var result = {
        /**
         * Manually invalidates the cached outcome.
         * @memberof CalculationCache#
         */
        invalidate: function () {
          cachedOutcome = undefined;
          cachedInputs = undefined;
        },
        /**
         * If the inputs array matches the inputs array from the previous invocation, this method returns the result of the previous invocation.
         * Otherwise, the calculation function is invoked and its result is cached and returned.
         * Objects in the inputs array are compared using ===.
         * @param {Object[]} inputs - Array of objects that are to be compared using === with the inputs from the previous invocation.
         * These objects are assumed to be immutable primitive values.
         * @param {function} calculation - Function that takes zero arguments and returns an object (A {@link VNode} assumably) that can be cached.
         * @memberof CalculationCache#
         */
        result: function (inputs, calculation) {
          if(cachedInputs) {
            for(var i = 0; i < inputs.length; i++) {
              if(cachedInputs[i] !== inputs[i]) {
                cachedOutcome = undefined;
              }
            }
          }
          if(!cachedOutcome) {
            cachedOutcome = calculation();
            cachedInputs = inputs;
          }
          return cachedOutcome;
        }
      };
      return result;
    },

    /**
     * Creates a {@link Mapping} instance that keeps an array of result objects synchronized with an array of source objects.
     * @param {function} getSourceKey - `function(source)` that must return a key to identify each source object. The result must eather be a string or a number.
     * @param {function} createResult - `function(source, index)` that must create a new result object from a given source. This function is identical argument of `Array.map`.
     * @param {function} updateResult - `function(source, target, index)` that updates a result to an updated source.
     * @returns {Mapping}
     */
    createMapping: function(getSourceKey, createResult, updateResult /*, deleteTarget*/) {
      var keys = [];
      var results = [];

      return {
        /**
         * The array of results. These results will be synchronized with the latest array of sources that were provided using {@link Mapping#map}.
         * @type {Object[]}
         * @memberof Mapping#
         */
        results: results,
        /**
         * Maps a new array of sources and updates {@link Mapping#results}.
         * @param {Object[]} newSources - The new array of sources.
         * @memberof Mapping#
         */
        map: function(newSources) {
          var newKeys = newSources.map(getSourceKey);
          var oldTargets = results.slice();
          var oldIndex = 0;
          for (var i=0;i<newSources.length;i++) {
            var source = newSources[i];
            var sourceKey = newKeys[i];
            if (sourceKey === keys[oldIndex]) {
              results[i] = oldTargets[oldIndex];
              updateResult(source, oldTargets[oldIndex], i);
              oldIndex++;
            } else {
              var found = false;
              for (var j = 1; j < keys.length; j++) {
                var searchIndex = (oldIndex + j) % keys.length;
                if (keys[searchIndex] === sourceKey) {
                  results[i] = oldTargets[searchIndex];
                  updateResult(newSources[i], oldTargets[searchIndex], i);
                  oldIndex = searchIndex + 1;
                  found = true;
                  break;
                }
              }
              if (!found) {
                results[i] = createResult(source, i);
              }
            }
          }
          results.length = newSources.length;
          keys = newKeys;
        }
      };
    },

    /**
     * Creates a {@link Projector} instance using the provided projectionOptions.
     * @param {Object} [projectionOptions] - Options that influence how the DOM is rendered and updated.
     * @param {Object} projectionOptions.transitions - A transition strategy to invoke when
     * enterAnimation and exitAnimation properties are provided as strings.
     * The module `cssTransitions` in the provided `css-transitions.js` file provides such a strategy.
     * A transition strategy is not needed when enterAnimation and exitAnimation properties are provided as functions.
     * @returns {Projector}
     */
    createProjector: function (projectionOptions) {
      projectionOptions = applyDefaultProjectionOptions(projectionOptions);
      projectionOptions.eventHandlerInterceptor = function (propertyName, functionPropertyArgument) {
        return function () {
          // intercept function calls (event handlers) to do a render afterwards.
          projector.scheduleRender();
          return functionPropertyArgument.apply(this, arguments);
        };
      };
      var renderCompleted = true;
      var scheduled;
      var stopped = false;
      var projections = [];
      var renderFunctions = []; // matches the projections array

      var doRender = function () {
        scheduled = undefined;
        if (!renderCompleted) {
          return; // The last render threw an error, it should be logged in the browser console.
        }
        var s = Date.now()
        renderCompleted = false;
        for(var i = 0; i < projections.length; i++) {
          var updatedVnode = renderFunctions[i]();
          projections[i].update(updatedVnode);
        }
        renderCompleted = true;
        if (Date.now()-s > 5)
          console.log("Render:", Date.now()-s)
      };

      var projector = {
        /**
         * Instructs the projector to re-render to the DOM at the next animation-frame using the registered `renderMaquette` functions.
         * This method is automatically called for you when event-handlers that are registered in the {@link VNode}s are invoked.
         * You need to call this method for instance when timeouts expire or AJAX responses arrive.
         * @memberof Projector#
         */
        scheduleRender: function () {
          if(!scheduled && !stopped) {
            scheduled = requestAnimationFrame(doRender);
          }
        },
        /**
         * Stops the projector. This means that the registered `renderMaquette` functions will not be called anymore.
         * Note that calling {@link Projector#stop} is not mandatory. A projector is a passive object that will get garbage collected as usual if it is no longer in scope.
         * @memberof Projector#
         */
        stop: function () {
          if(scheduled) {
            cancelAnimationFrame(scheduled);
            scheduled = undefined;
          }
          stopped = true;
        },
        /**
         * Resumes the projector. Use this method to resume rendering after stop was called or an error occurred during rendering.
         * @memberof Projector#
         */
        resume: function() {
          stopped = false;
          renderCompleted = true;
          projector.scheduleRender();
        },
        /**
         * Scans the document for `<script>` tags with `type="text/hyperscript"`.
         * The content of these scripts are registered as `renderMaquette` functions.
         * The result of evaluating these functions will be inserted into the DOM after the script.
         * These scripts can make use of variables that come from the `parameters` parameter.
         * @param {Element} rootNode - Element to start scanning at, example: `document.body`.
         * @param {Object} parameters - Variables to expose to the scripts. format: `{var1:value1, var2: value2}`
         * @memberof Projector#
         */
        evaluateHyperscript: function (rootNode, parameters) {
          var nodes = rootNode.querySelectorAll("script[type='text/hyperscript']");
          var functionParameters = ["maquette", "h", "enhancer"];
          var parameterValues = [maquette, maquette.h, projector];
          Object.keys(parameters).forEach(function (parameterName) {
            functionParameters.push(parameterName);
            parameterValues.push(parameters[parameterName]);
          });
          Array.prototype.forEach.call(nodes, function (node) {
            var func = new Function(functionParameters, "return " + node.textContent.trim());
            var renderFunction = function () {
              return func.apply(undefined, parameterValues);
            };
            projector.insertBefore(node, renderFunction);
          });
        },
        /**
         * Appends a new childnode to the DOM using the result from the provided `renderMaquetteFunction`.
         * The `renderMaquetteFunction` will be invoked again to update the DOM when needed.
         * @param {Element} parentNode - The parent node for the new childNode.
         * @param {function} renderMaquetteFunction - Function with zero arguments that returns a {@link VNode} tree.
         * @memberof Projector#
         */
        append: function (parentNode, renderMaquetteFunction) {
          projections.push(maquette.dom.append(parentNode, renderMaquetteFunction(), projectionOptions));
          renderFunctions.push(renderMaquetteFunction);
        },
        /**
         * Inserts a new DOM node using the result from the provided `renderMaquetteFunction`.
         * The `renderMaquetteFunction` will be invoked again to update the DOM when needed.
         * @param {Element} beforeNode - The node that the DOM Node is inserted before.
         * @param {function} renderMaquetteFunction - Function with zero arguments that returns a {@link VNode} tree.
         * @memberof Projector#
         */
        insertBefore: function (beforeNode, renderMaquetteFunction) {
          projections.push(maquette.dom.insertBefore(beforeNode, renderMaquetteFunction(), projectionOptions));
          renderFunctions.push(renderMaquetteFunction);
        },
        /**
         * Merges a new DOM node using the result from the provided `renderMaquetteFunction` with an existing DOM Node.
         * This means that the virtual DOM and real DOM have one overlapping element.
         * Therefore the selector for the root {@link VNode} will be ignored, but its properties and children will be applied to the Element provided
         * The `renderMaquetteFunction` will be invoked again to update the DOM when needed.
         * @param {Element} domNode - The existing element to adopt as the root of the new virtual DOM. Existing attributes and childnodes are preserved.
         * @param {function} renderMaquetteFunction - Function with zero arguments that returns a {@link VNode} tree.
         * @memberof Projector#
         */
        merge: function (domNode, renderMaquetteFunction) {
          projections.push(maquette.dom.merge(domNode, renderMaquetteFunction(), projectionOptions));
          renderFunctions.push(renderMaquetteFunction);
        },
        /**
         * Replaces an existing DOM node with the result from the provided `renderMaquetteFunction`.
         * The `renderMaquetteFunction` will be invoked again to update the DOM when needed.
         * @param {Element} domNode - The DOM node to replace.
         * @param {function} renderMaquetteFunction - Function with zero arguments that returns a {@link VNode} tree.
         * @memberof Projector#
         */
        replace: function (domNode, renderMaquetteFunction) {
          var vnode = renderMaquetteFunction();
          createDom(vnode, domNode.parentNode, domNode, projectionOptions);
          domNode.parentNode.removeChild(domNode);
          projections.push(createProjection(vnode, projectionOptions));
          renderFunctions.push(renderMaquetteFunction);
        }
      };
      return projector;
    }
  };

  if(typeof module !== "undefined" && module.exports) {
    // Node and other CommonJS-like environments that support module.exports
    module.exports = maquette;
  } else if(typeof define === "function" && define.amd) {
    // AMD / RequireJS
    define(function () {
      return maquette;
    });
  } else {
    // Browser
    window.maquette = maquette;
  }

})(this);



/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/lib/marked.min.js ---- */


/**
 * marked - a markdown parser
 * Copyright (c) 2011-2014, Christopher Jeffrey. (MIT Licensed)
 * https://github.com/chjj/marked
 */
(function(){var block={newline:/^\n+/,code:/^( {4}[^\n]+\n*)+/,fences:noop,hr:/^( *[-*_]){3,} *(?:\n+|$)/,heading:/^ *(#{1,6}) *([^\n]+?) *#* *(?:\n+|$)/,nptable:noop,lheading:/^([^\n]+)\n *(=|-){2,} *(?:\n+|$)/,blockquote:/^( *>[^\n]+(\n(?!def)[^\n]+)*\n*)+/,list:/^( *)(bull) [\s\S]+?(?:hr|def|\n{2,}(?! )(?!\1bull )\n*|\s*$)/,html:/^ *(?:comment|closed|closing) *(?:\n{2,}|\s*$)/,def:/^ *\[([^\]]+)\]: *<?([^\s>]+)>?(?: +["(]([^\n]+)[")])? *(?:\n+|$)/,table:noop,paragraph:/^((?:[^\n]+\n?(?!hr|heading|lheading|blockquote|tag|def))+)\n*/,text:/^[^\n]+/};block.bullet=/(?:[*+-]|\d+\.)/;block.item=/^( *)(bull) [^\n]*(?:\n(?!\1bull )[^\n]*)*/;block.item=replace(block.item,"gm")(/bull/g,block.bullet)();block.list=replace(block.list)(/bull/g,block.bullet)("hr","\\n+(?=\\1?(?:[-*_] *){3,}(?:\\n+|$))")("def","\\n+(?="+block.def.source+")")();block.blockquote=replace(block.blockquote)("def",block.def)();block._tag="(?!(?:"+"a|em|strong|small|s|cite|q|dfn|abbr|data|time|code"+"|var|samp|kbd|sub|sup|i|b|u|mark|ruby|rt|rp|bdi|bdo"+"|span|br|wbr|ins|del|img)\\b)\\w+(?!:/|[^\\w\\s@]*@)\\b";block.html=replace(block.html)("comment",/<!--[\s\S]*?-->/)("closed",/<(tag)[\s\S]+?<\/\1>/)("closing",/<tag(?:"[^"]*"|'[^']*'|[^'">])*?>/)(/tag/g,block._tag)();block.paragraph=replace(block.paragraph)("hr",block.hr)("heading",block.heading)("lheading",block.lheading)("blockquote",block.blockquote)("tag","<"+block._tag)("def",block.def)();block.normal=merge({},block);block.gfm=merge({},block.normal,{fences:/^ *(`{3,}|~{3,}) *(\S+)? *\n([\s\S]+?)\s*\1 *(?:\n+|$)/,paragraph:/^/});block.gfm.paragraph=replace(block.paragraph)("(?!","(?!"+block.gfm.fences.source.replace("\\1","\\2")+"|"+block.list.source.replace("\\1","\\3")+"|")();block.tables=merge({},block.gfm,{nptable:/^ *(\S.*\|.*)\n *([-:]+ *\|[-| :]*)\n((?:.*\|.*(?:\n|$))*)\n*/,table:/^ *\|(.+)\n *\|( *[-:]+[-| :]*)\n((?: *\|.*(?:\n|$))*)\n*/});function Lexer(options){this.tokens=[];this.tokens.links={};this.options=options||marked.defaults;this.rules=block.normal;if(this.options.gfm){if(this.options.tables){this.rules=block.tables}else{this.rules=block.gfm}}}Lexer.rules=block;Lexer.lex=function(src,options){var lexer=new Lexer(options);return lexer.lex(src)};Lexer.prototype.lex=function(src){src=src.replace(/\r\n|\r/g,"\n").replace(/\t/g,"    ").replace(/\u00a0/g," ").replace(/\u2424/g,"\n");return this.token(src,true)};Lexer.prototype.token=function(src,top,bq){var src=src.replace(/^ +$/gm,""),next,loose,cap,bull,b,item,space,i,l;while(src){if(cap=this.rules.newline.exec(src)){src=src.substring(cap[0].length);if(cap[0].length>1){this.tokens.push({type:"space"})}}if(cap=this.rules.code.exec(src)){src=src.substring(cap[0].length);cap=cap[0].replace(/^ {4}/gm,"");this.tokens.push({type:"code",text:!this.options.pedantic?cap.replace(/\n+$/,""):cap});continue}if(cap=this.rules.fences.exec(src)){src=src.substring(cap[0].length);this.tokens.push({type:"code",lang:cap[2],text:cap[3]});continue}if(cap=this.rules.heading.exec(src)){src=src.substring(cap[0].length);this.tokens.push({type:"heading",depth:cap[1].length,text:cap[2]});continue}if(top&&(cap=this.rules.nptable.exec(src))){src=src.substring(cap[0].length);item={type:"table",header:cap[1].replace(/^ *| *\| *$/g,"").split(/ *\| */),align:cap[2].replace(/^ *|\| *$/g,"").split(/ *\| */),cells:cap[3].replace(/\n$/,"").split("\n")};for(i=0;i<item.align.length;i++){if(/^ *-+: *$/.test(item.align[i])){item.align[i]="right"}else if(/^ *:-+: *$/.test(item.align[i])){item.align[i]="center"}else if(/^ *:-+ *$/.test(item.align[i])){item.align[i]="left"}else{item.align[i]=null}}for(i=0;i<item.cells.length;i++){item.cells[i]=item.cells[i].split(/ *\| */)}this.tokens.push(item);continue}if(cap=this.rules.lheading.exec(src)){src=src.substring(cap[0].length);this.tokens.push({type:"heading",depth:cap[2]==="="?1:2,text:cap[1]});continue}if(cap=this.rules.hr.exec(src)){src=src.substring(cap[0].length);this.tokens.push({type:"hr"});continue}if(cap=this.rules.blockquote.exec(src)){src=src.substring(cap[0].length);this.tokens.push({type:"blockquote_start"});cap=cap[0].replace(/^ *> ?/gm,"");this.token(cap,top,true);this.tokens.push({type:"blockquote_end"});continue}if(cap=this.rules.list.exec(src)){src=src.substring(cap[0].length);bull=cap[2];this.tokens.push({type:"list_start",ordered:bull.length>1});cap=cap[0].match(this.rules.item);next=false;l=cap.length;i=0;for(;i<l;i++){item=cap[i];space=item.length;item=item.replace(/^ *([*+-]|\d+\.) +/,"");if(~item.indexOf("\n ")){space-=item.length;item=!this.options.pedantic?item.replace(new RegExp("^ {1,"+space+"}","gm"),""):item.replace(/^ {1,4}/gm,"")}if(this.options.smartLists&&i!==l-1){b=block.bullet.exec(cap[i+1])[0];if(bull!==b&&!(bull.length>1&&b.length>1)){src=cap.slice(i+1).join("\n")+src;i=l-1}}loose=next||/\n\n(?!\s*$)/.test(item);if(i!==l-1){next=item.charAt(item.length-1)==="\n";if(!loose)loose=next}this.tokens.push({type:loose?"loose_item_start":"list_item_start"});this.token(item,false,bq);this.tokens.push({type:"list_item_end"})}this.tokens.push({type:"list_end"});continue}if(cap=this.rules.html.exec(src)){src=src.substring(cap[0].length);this.tokens.push({type:this.options.sanitize?"paragraph":"html",pre:cap[1]==="pre"||cap[1]==="script"||cap[1]==="style",text:cap[0]});continue}if(!bq&&top&&(cap=this.rules.def.exec(src))){src=src.substring(cap[0].length);this.tokens.links[cap[1].toLowerCase()]={href:cap[2],title:cap[3]};continue}if(top&&(cap=this.rules.table.exec(src))){src=src.substring(cap[0].length);item={type:"table",header:cap[1].replace(/^ *| *\| *$/g,"").split(/ *\| */),align:cap[2].replace(/^ *|\| *$/g,"").split(/ *\| */),cells:cap[3].replace(/(?: *\| *)?\n$/,"").split("\n")};for(i=0;i<item.align.length;i++){if(/^ *-+: *$/.test(item.align[i])){item.align[i]="right"}else if(/^ *:-+: *$/.test(item.align[i])){item.align[i]="center"}else if(/^ *:-+ *$/.test(item.align[i])){item.align[i]="left"}else{item.align[i]=null}}for(i=0;i<item.cells.length;i++){item.cells[i]=item.cells[i].replace(/^ *\| *| *\| *$/g,"").split(/ *\| */)}this.tokens.push(item);continue}if(top&&(cap=this.rules.paragraph.exec(src))){src=src.substring(cap[0].length);this.tokens.push({type:"paragraph",text:cap[1].charAt(cap[1].length-1)==="\n"?cap[1].slice(0,-1):cap[1]});continue}if(cap=this.rules.text.exec(src)){src=src.substring(cap[0].length);this.tokens.push({type:"text",text:cap[0]});continue}if(src){throw new Error("Infinite loop on byte: "+src.charCodeAt(0))}}return this.tokens};var inline={escape:/^\\([\\`*{}\[\]()#+\-.!_>])/,autolink:/^<([^ >]+(@|:\/)[^ >]+)>/,url:noop,tag:/^<!--[\s\S]*?-->|^<\/?\w+(?:"[^"]*"|'[^']*'|[^'">])*?>/,link:/^!?\[(inside)\]\(href\)/,reflink:/^!?\[(inside)\]\s*\[([^\]]*)\]/,nolink:/^!?\[((?:\[[^\]]*\]|[^\[\]])*)\]/,strong:/^__([\s\S]+?)__(?!_)|^\*\*([\s\S]+?)\*\*(?!\*)/,em:/^\b_((?:__|[\s\S])+?)_\b|^\*((?:\*\*|[\s\S])+?)\*(?!\*)/,code:/^(`+)\s*([\s\S]*?[^`])\s*\1(?!`)/,br:/^ {2,}\n(?!\s*$)/,del:noop,text:/^[\s\S]+?(?=[\\<!\[_*`]| {2,}\n|$)/};inline._inside=/(?:\[[^\]]*\]|[^\[\]]|\](?=[^\[]*\]))*/;inline._href=/\s*<?([\s\S]*?)>?(?:\s+['"]([\s\S]*?)['"])?\s*/;inline.link=replace(inline.link)("inside",inline._inside)("href",inline._href)();inline.reflink=replace(inline.reflink)("inside",inline._inside)();inline.normal=merge({},inline);inline.pedantic=merge({},inline.normal,{strong:/^__(?=\S)([\s\S]*?\S)__(?!_)|^\*\*(?=\S)([\s\S]*?\S)\*\*(?!\*)/,em:/^_(?=\S)([\s\S]*?\S)_(?!_)|^\*(?=\S)([\s\S]*?\S)\*(?!\*)/});inline.gfm=merge({},inline.normal,{escape:replace(inline.escape)("])","~|])")(),url:/^(https?:\/\/[^\s<]+[^<.,:;"')\]\s])/,del:/^~~(?=\S)([\s\S]*?\S)~~/,text:replace(inline.text)("]|","~]|")("|","|https?://|")()});inline.breaks=merge({},inline.gfm,{br:replace(inline.br)("{2,}","*")(),text:replace(inline.gfm.text)("{2,}","*")()});function InlineLexer(links,options){this.options=options||marked.defaults;this.links=links;this.rules=inline.normal;this.renderer=this.options.renderer||new Renderer;this.renderer.options=this.options;if(!this.links){throw new Error("Tokens array requires a `links` property.")}if(this.options.gfm){if(this.options.breaks){this.rules=inline.breaks}else{this.rules=inline.gfm}}else if(this.options.pedantic){this.rules=inline.pedantic}}InlineLexer.rules=inline;InlineLexer.output=function(src,links,options){var inline=new InlineLexer(links,options);return inline.output(src)};InlineLexer.prototype.output=function(src){var out="",link,text,href,cap;while(src){if(cap=this.rules.escape.exec(src)){src=src.substring(cap[0].length);out+=cap[1];continue}if(cap=this.rules.autolink.exec(src)){src=src.substring(cap[0].length);if(cap[2]==="@"){text=cap[1].charAt(6)===":"?this.mangle(cap[1].substring(7)):this.mangle(cap[1]);href=this.mangle("mailto:")+text}else{text=escape(cap[1]);href=text}out+=this.renderer.link(href,null,text);continue}if(!this.inLink&&(cap=this.rules.url.exec(src))){src=src.substring(cap[0].length);text=escape(cap[1]);href=text;out+=this.renderer.link(href,null,text);continue}if(cap=this.rules.tag.exec(src)){if(!this.inLink&&/^<a /i.test(cap[0])){this.inLink=true}else if(this.inLink&&/^<\/a>/i.test(cap[0])){this.inLink=false}src=src.substring(cap[0].length);out+=this.options.sanitize?escape(cap[0]):cap[0];continue}if(cap=this.rules.link.exec(src)){src=src.substring(cap[0].length);this.inLink=true;out+=this.outputLink(cap,{href:cap[2],title:cap[3]});this.inLink=false;continue}if((cap=this.rules.reflink.exec(src))||(cap=this.rules.nolink.exec(src))){src=src.substring(cap[0].length);link=(cap[2]||cap[1]).replace(/\s+/g," ");link=this.links[link.toLowerCase()];if(!link||!link.href){out+=cap[0].charAt(0);src=cap[0].substring(1)+src;continue}this.inLink=true;out+=this.outputLink(cap,link);this.inLink=false;continue}if(cap=this.rules.strong.exec(src)){src=src.substring(cap[0].length);out+=this.renderer.strong(this.output(cap[2]||cap[1]));continue}if(cap=this.rules.em.exec(src)){src=src.substring(cap[0].length);out+=this.renderer.em(this.output(cap[2]||cap[1]));continue}if(cap=this.rules.code.exec(src)){src=src.substring(cap[0].length);out+=this.renderer.codespan(escape(cap[2],true));continue}if(cap=this.rules.br.exec(src)){src=src.substring(cap[0].length);out+=this.renderer.br();continue}if(cap=this.rules.del.exec(src)){src=src.substring(cap[0].length);out+=this.renderer.del(this.output(cap[1]));continue}if(cap=this.rules.text.exec(src)){src=src.substring(cap[0].length);out+=escape(this.smartypants(cap[0]));continue}if(src){throw new Error("Infinite loop on byte: "+src.charCodeAt(0))}}return out};InlineLexer.prototype.outputLink=function(cap,link){var href=escape(link.href),title=link.title?escape(link.title):null;return cap[0].charAt(0)!=="!"?this.renderer.link(href,title,this.output(cap[1])):this.renderer.image(href,title,escape(cap[1]))};InlineLexer.prototype.smartypants=function(text){if(!this.options.smartypants)return text;return text.replace(/--/g,"—").replace(/(^|[-\u2014/(\[{"\s])'/g,"$1‘").replace(/'/g,"’").replace(/(^|[-\u2014/(\[{\u2018\s])"/g,"$1“").replace(/"/g,"”").replace(/\.{3}/g,"…")};InlineLexer.prototype.mangle=function(text){var out="",l=text.length,i=0,ch;for(;i<l;i++){ch=text.charCodeAt(i);if(Math.random()>.5){ch="x"+ch.toString(16)}out+="&#"+ch+";"}return out};function Renderer(options){this.options=options||{}}Renderer.prototype.code=function(code,lang,escaped){if(this.options.highlight){var out=this.options.highlight(code,lang);if(out!=null&&out!==code){escaped=true;code=out}}if(!lang){return"<pre><code>"+(escaped?code:escape(code,true))+"\n</code></pre>"}return'<pre><code class="'+this.options.langPrefix+escape(lang,true)+'">'+(escaped?code:escape(code,true))+"\n</code></pre>\n"};Renderer.prototype.blockquote=function(quote){return"<blockquote>\n"+quote+"</blockquote>\n"};Renderer.prototype.html=function(html){return html};Renderer.prototype.heading=function(text,level,raw){return"<h"+level+' id="'+this.options.headerPrefix+raw.toLowerCase().replace(/[^\w]+/g,"-")+'">'+text+"</h"+level+">\n"};Renderer.prototype.hr=function(){return this.options.xhtml?"<hr/>\n":"<hr>\n"};Renderer.prototype.list=function(body,ordered){var type=ordered?"ol":"ul";return"<"+type+">\n"+body+"</"+type+">\n"};Renderer.prototype.listitem=function(text){return"<li>"+text+"</li>\n"};Renderer.prototype.paragraph=function(text){return"<p>"+text+"</p>\n"};Renderer.prototype.table=function(header,body){return"<table>\n"+"<thead>\n"+header+"</thead>\n"+"<tbody>\n"+body+"</tbody>\n"+"</table>\n"};Renderer.prototype.tablerow=function(content){return"<tr>\n"+content+"</tr>\n"};Renderer.prototype.tablecell=function(content,flags){var type=flags.header?"th":"td";var tag=flags.align?"<"+type+' style="text-align:'+flags.align+'">':"<"+type+">";return tag+content+"</"+type+">\n"};Renderer.prototype.strong=function(text){return"<strong>"+text+"</strong>"};Renderer.prototype.em=function(text){return"<em>"+text+"</em>"};Renderer.prototype.codespan=function(text){return"<code>"+text+"</code>"};Renderer.prototype.br=function(){return this.options.xhtml?"<br/>":"<br>"};Renderer.prototype.del=function(text){return"<del>"+text+"</del>"};Renderer.prototype.link=function(href,title,text){if(this.options.sanitize){try{var prot=decodeURIComponent(unescape(href)).replace(/[^\w:]/g,"").toLowerCase()}catch(e){return""}if(prot.indexOf("javascript:")===0){return""}}var out='<a href="'+href+'"';if(title){out+=' title="'+title+'"'}out+=">"+text+"</a>";return out};Renderer.prototype.image=function(href,title,text){var out='<img src="'+href+'" alt="'+text+'"';if(title){out+=' title="'+title+'"'}out+=this.options.xhtml?"/>":">";return out};function Parser(options){this.tokens=[];this.token=null;this.options=options||marked.defaults;this.options.renderer=this.options.renderer||new Renderer;this.renderer=this.options.renderer;this.renderer.options=this.options}Parser.parse=function(src,options,renderer){var parser=new Parser(options,renderer);return parser.parse(src)};Parser.prototype.parse=function(src){this.inline=new InlineLexer(src.links,this.options,this.renderer);this.tokens=src.reverse();var out="";while(this.next()){out+=this.tok()}return out};Parser.prototype.next=function(){return this.token=this.tokens.pop()};Parser.prototype.peek=function(){return this.tokens[this.tokens.length-1]||0};Parser.prototype.parseText=function(){var body=this.token.text;while(this.peek().type==="text"){body+="\n"+this.next().text}return this.inline.output(body)};Parser.prototype.tok=function(){switch(this.token.type){case"space":{return""}case"hr":{return this.renderer.hr()}case"heading":{return this.renderer.heading(this.inline.output(this.token.text),this.token.depth,this.token.text)}case"code":{return this.renderer.code(this.token.text,this.token.lang,this.token.escaped)}case"table":{var header="",body="",i,row,cell,flags,j;cell="";for(i=0;i<this.token.header.length;i++){flags={header:true,align:this.token.align[i]};cell+=this.renderer.tablecell(this.inline.output(this.token.header[i]),{header:true,align:this.token.align[i]})}header+=this.renderer.tablerow(cell);for(i=0;i<this.token.cells.length;i++){row=this.token.cells[i];cell="";for(j=0;j<row.length;j++){cell+=this.renderer.tablecell(this.inline.output(row[j]),{header:false,align:this.token.align[j]})}body+=this.renderer.tablerow(cell)}return this.renderer.table(header,body)}case"blockquote_start":{var body="";while(this.next().type!=="blockquote_end"){body+=this.tok()}return this.renderer.blockquote(body)}case"list_start":{var body="",ordered=this.token.ordered;while(this.next().type!=="list_end"){body+=this.tok()}return this.renderer.list(body,ordered)}case"list_item_start":{var body="";while(this.next().type!=="list_item_end"){body+=this.token.type==="text"?this.parseText():this.tok()}return this.renderer.listitem(body)}case"loose_item_start":{var body="";while(this.next().type!=="list_item_end"){body+=this.tok()}return this.renderer.listitem(body)}case"html":{var html=!this.token.pre&&!this.options.pedantic?this.inline.output(this.token.text):this.token.text;return this.renderer.html(html)}case"paragraph":{return this.renderer.paragraph(this.inline.output(this.token.text))}case"text":{return this.renderer.paragraph(this.parseText())}}};function escape(html,encode){return html.replace(!encode?/&(?!#?\w+;)/g:/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")}function unescape(html){return html.replace(/&([#\w]+);/g,function(_,n){n=n.toLowerCase();if(n==="colon")return":";if(n.charAt(0)==="#"){return n.charAt(1)==="x"?String.fromCharCode(parseInt(n.substring(2),16)):String.fromCharCode(+n.substring(1))}return""})}function replace(regex,opt){regex=regex.source;opt=opt||"";return function self(name,val){if(!name)return new RegExp(regex,opt);val=val.source||val;val=val.replace(/(^|[^\[])\^/g,"$1");regex=regex.replace(name,val);return self}}function noop(){}noop.exec=noop;function merge(obj){var i=1,target,key;for(;i<arguments.length;i++){target=arguments[i];for(key in target){if(Object.prototype.hasOwnProperty.call(target,key)){obj[key]=target[key]}}}return obj}function marked(src,opt,callback){if(callback||typeof opt==="function"){if(!callback){callback=opt;opt=null}opt=merge({},marked.defaults,opt||{});var highlight=opt.highlight,tokens,pending,i=0;try{tokens=Lexer.lex(src,opt)}catch(e){return callback(e)}pending=tokens.length;var done=function(err){if(err){opt.highlight=highlight;return callback(err)}var out;try{out=Parser.parse(tokens,opt)}catch(e){err=e}opt.highlight=highlight;return err?callback(err):callback(null,out)};if(!highlight||highlight.length<3){return done()}delete opt.highlight;if(!pending)return done();for(;i<tokens.length;i++){(function(token){if(token.type!=="code"){return--pending||done()}return highlight(token.text,token.lang,function(err,code){if(err)return done(err);if(code==null||code===token.text){return--pending||done()}token.text=code;token.escaped=true;--pending||done()})})(tokens[i])}return}try{if(opt)opt=merge({},marked.defaults,opt);return Parser.parse(Lexer.lex(src,opt),opt)}catch(e){e.message+="\nPlease report this to https://github.com/chjj/marked.";if((opt||marked.defaults).silent){return"<p>An error occured:</p><pre>"+escape(e.message+"",true)+"</pre>"}throw e}}marked.options=marked.setOptions=function(opt){merge(marked.defaults,opt);return marked};marked.defaults={gfm:true,tables:true,breaks:false,pedantic:false,sanitize:false,smartLists:false,silent:false,highlight:null,langPrefix:"lang-",smartypants:false,headerPrefix:"",renderer:new Renderer,xhtml:false};marked.Parser=Parser;marked.parser=Parser.parse;marked.Renderer=Renderer;marked.Lexer=Lexer;marked.lexer=Lexer.lex;marked.InlineLexer=InlineLexer;marked.inlineLexer=InlineLexer.output;marked.parse=marked;if(typeof module!=="undefined"&&typeof exports==="object"){module.exports=marked}else if(typeof define==="function"&&define.amd){define(function(){return marked})}else{this.marked=marked}}).call(function(){return this||(typeof window!=="undefined"?window:global)}());


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/utils/Animation.coffee ---- */


(function() {
  var Animation;

  Animation = (function() {
    function Animation() {}

    Animation.prototype.slideDown = function(elem, props) {
      var cstyle, h, margin_bottom, margin_top, padding_bottom, padding_top, transition;
      if (props.disableAnimation) {
        return;
      }
      h = elem.offsetHeight;
      cstyle = window.getComputedStyle(elem);
      margin_top = cstyle.marginTop;
      margin_bottom = cstyle.marginBottom;
      padding_top = cstyle.paddingTop;
      padding_bottom = cstyle.paddingBottom;
      transition = cstyle.transition;
      elem.style.boxSizing = "border-box";
      elem.style.overflow = "hidden";
      elem.style.transform = "scale(0.8)";
      elem.style.opacity = "0";
      elem.style.height = "0px";
      elem.style.marginTop = "0px";
      elem.style.marginBottom = "0px";
      elem.style.paddingTop = "0px";
      elem.style.paddingBottom = "0px";
      elem.style.transition = "none";
      setTimeout((function() {
        elem.className += " animate-back";
        elem.style.height = h + "px";
        elem.style.transform = "scale(1)";
        elem.style.opacity = "1";
        elem.style.marginTop = margin_top;
        elem.style.marginBottom = margin_bottom;
        elem.style.paddingTop = padding_top;
        return elem.style.paddingBottom = padding_bottom;
      }), 1);
      return elem.addEventListener("transitionend", function() {
        elem.classList.remove("animate-back");
        elem.style.transition = elem.style.transform = elem.style.opacity = elem.style.height = null;
        elem.style.boxSizing = elem.style.marginTop = elem.style.marginBottom = null;
        return elem.style.paddingTop = elem.style.paddingBottom = elem.style.overflow = null;
      });
    };

    Animation.prototype.slideUp = function(elem, remove_func, props) {
      elem.className += " animate-back";
      elem.style.boxSizing = "border-box";
      elem.style.height = elem.offsetHeight + "px";
      elem.style.overflow = "hidden";
      elem.style.transform = "scale(1)";
      elem.style.opacity = "1";
      setTimeout((function() {
        elem.style.height = "0px";
        elem.style.marginTop = "0px";
        elem.style.marginBottom = "0px";
        elem.style.paddingTop = "0px";
        elem.style.paddingBottom = "0px";
        elem.style.transform = "scale(0.8)";
        elem.style.borderTopWidth = "0px";
        elem.style.borderBottomWidth = "0px";
        return elem.style.opacity = "0";
      }), 1);
      return elem.addEventListener("transitionend", remove_func);
    };

    Animation.prototype.showRight = function(elem, props) {
      elem.className += " animate";
      elem.style.opacity = 0;
      elem.style.transform = "TranslateX(-20px) Scale(1.01)";
      setTimeout((function() {
        elem.style.opacity = 1;
        return elem.style.transform = "TranslateX(0px) Scale(1)";
      }), 1);
      return elem.addEventListener("transitionend", function() {
        elem.classList.remove("animate");
        return elem.style.transform = elem.style.opacity = null;
      });
    };

    Animation.prototype.show = function(elem, props) {
      var delay, _ref;
      delay = ((_ref = arguments[arguments.length - 2]) != null ? _ref.delay : void 0) * 1000 || 1;
      elem.className += " animate";
      elem.style.opacity = 0;
      setTimeout((function() {
        return elem.style.opacity = 1;
      }), delay);
      return elem.addEventListener("transitionend", function() {
        elem.classList.remove("animate");
        return elem.style.opacity = null;
      });
    };

    Animation.prototype.addVisibleClass = function(elem, props) {
      return setTimeout(function() {
        return elem.classList.add("visible");
      });
    };

    Animation.prototype.termLines = function(elem, projection_options, selector, props) {
      var back, delay, delay_step, line, lines, _i, _len;
      lines = elem.innerHTML.split("\n");
      delay = props.delay || 0;
      delay_step = props.delay_step || 0.05;
      back = [];
      for (_i = 0, _len = lines.length; _i < _len; _i++) {
        line = lines[_i];
        line = line.replace(/(\.+)(.*?)$/, "<span class='dots'>$1</span><span class='result'>$2</span>", line);
        back.push("<span style='transition-delay: " + delay + "s'>" + line + "</span>");
        delay += delay_step;
      }
      setTimeout((function() {
        return elem.classList.add("visible");
      }), 100);
      return elem.innerHTML = back.join("\n");
    };

    Animation.prototype.scramble = function(elem) {
      var chars, frame, replaces, text_original, timer;
      text_original = elem.value;
      chars = elem.value.split("");
      chars = chars.filter(function(char) {
        return char !== "\n" && char !== "\r" && char !== " " && char !== "​";
      });
      replaces = ["⠋", '⠙', '⠹', '⠒', '⠔', '⠃', '⡳', '⠁', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
      replaces.sort(function() {
        return 0.5 - Math.random();
      });
      frame = 0;
      return timer = setInterval((function() {
        var char, i, _i, _ref;
        for (i = _i = 0, _ref = Math.round(text_original.length / 20); 0 <= _ref ? _i <= _ref : _i >= _ref; i = 0 <= _ref ? ++_i : --_i) {
          char = chars.shift();
          elem.value = elem.value.replace(char, replaces[(frame + i) % replaces.length]);
        }
        if (chars.length === 0) {
          clearInterval(timer);
        }
        return frame += 1;
      }), 50);
    };


    /*
    	showScramble: (elem, props) ->
    		text_original = elem.innerText
    
    		chars = elem.innerText.split("")
    
    		 * Convert characters to whitespace
    		clear_chars = chars.map (char) ->
    			if char != "\n" and char != "\r" and char != " " and char != "​"
    				return " "
    			else
    				return char
    		elem.innerText = clear_chars.join("")
    
    		replaces = ["|", "[", "]", "/", "\\", "*", "-", "$", "~", "^", "#", ">", "<", "(", ")", "+", "%", "=", "!"]
    		replaces.sort ->
    			return 0.5-Math.random()
    
    		frame = 0
    		timer = 0
    		replace_show = ->
    			for i in [0..10]
    				replace = replaces[Math.floor(Math.random()*(replaces.length-1))]
    				elem.innerText = elem.innerText.replace(" ", replace)
    				elem.innerText = elem.innerText.replace(replace, replaces[frame % (replaces.length-1)])
    			frame += 1
    			if frame > chars.length/10
    				clearInterval(timer)
    				timer = setInterval text_show, 20
    
    		text_show = ->
    			for i in [0..10]
    
    
    			clearInterval(timer)
    
    		timer = setInterval replace_show, 20
    
    
    	scramble2: (elem, props) ->
    		text_original = elem.innerText
    		chars = elem.innerText.split("")
    		chars_num = chars.length
    		frame = 0
    		timer = setInterval ( ->
    			for replace in ["|", "[", "]", "/", "\\", "*", "-", "$", "~", "^", "#", ">", "<", "(", ")", "+", "%", "=", "!"]
    				index = Math.round(Math.random()*chars_num)
    				if chars[index] != "\n" and chars[index] != "\r" and chars[index] != " " and chars[index] != "​" # Null character
    					chars[index] = replace
    			elem.innerText = chars.join("")
    			frame += 1
    			if frame > 100
    				clearInterval(timer)
    		), 20
    		@
     */

    return Animation;

  })();

  window.Animation = new Animation();

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/utils/Autocomplete.coffee ---- */


(function() {
  var Autocomplete,
    __bind = function(fn, me){ return function(){ return fn.apply(me, arguments); }; };

  Autocomplete = (function() {
    function Autocomplete(_at_getValues, _at_attrs, _at_onChanged) {
      this.getValues = _at_getValues;
      this.attrs = _at_attrs != null ? _at_attrs : {};
      this.onChanged = _at_onChanged != null ? _at_onChanged : null;
      this.handleBlur = __bind(this.handleBlur, this);
      this.handleFocus = __bind(this.handleFocus, this);
      this.handleClick = __bind(this.handleClick, this);
      this.handleKey = __bind(this.handleKey, this);
      this.handleInput = __bind(this.handleInput, this);
      this.filterValues = __bind(this.filterValues, this);
      this.setNode = __bind(this.setNode, this);
      this.attrs.oninput = this.handleInput;
      this.attrs.onfocus = this.handleFocus;
      this.attrs.onblur = this.handleBlur;
      this.attrs.onkeydown = this.handleKey;
      this.values = [];
      this.selected_index = 0;
      this.focus = false;
    }

    Autocomplete.prototype.setNode = function(node) {
      return this.node = node;
    };

    Autocomplete.prototype.setValue = function(value) {
      this.attrs.value = value;
      if (this.onChanged) {
        this.onChanged(value);
      }
      return Page.projector.scheduleRender();
    };

    Autocomplete.prototype.filterValues = function(filter) {
      var current_value, distance, match, parts, re_highlight, res, row, value, values, _i, _len;
      current_value = this.attrs.value;
      values = this.getValues();
      re_highlight = new RegExp("^(.*?)(" + filter.split("").join(")(.*?)(") + ")(.*?)$", "i");
      res = [];
      for (_i = 0, _len = values.length; _i < _len; _i++) {
        value = values[_i];
        distance = Text.distance(value, current_value);
        if (distance !== false) {
          match = value.match(re_highlight);
          if (!match) {
            continue;
          }
          parts = match.map(function(part, i) {
            if (i % 2 === 0) {
              return "<b>" + part + "</b>";
            } else {
              return part;
            }
          });
          parts.shift();
          res.push([parts.join(""), distance]);
        }
      }
      res.sort(function(a, b) {
        return a[1] - b[1];
      });
      this.values = (function() {
        var _j, _len1, _ref, _results;
        _ref = res.slice(0, 10);
        _results = [];
        for (_j = 0, _len1 = _ref.length; _j < _len1; _j++) {
          row = _ref[_j];
          _results.push(row[0]);
        }
        return _results;
      })();
      return this.values;
    };

    Autocomplete.prototype.renderValue = function(node, projector_options, children, attrs) {
      return node.innerHTML = attrs.key;
    };

    Autocomplete.prototype.handleInput = function(e) {
      this.attrs.value = e.target.value;
      this.selected_index = 0;
      return this.focus = true;
    };

    Autocomplete.prototype.handleKey = function(e) {
      if (e.keyCode === 38) {
        this.selected_index = Math.max(0, this.selected_index - 1);
        return false;
      } else if (e.keyCode === 40) {
        this.selected_index = Math.min(this.values.length - 1, this.selected_index + 1);
        return false;
      } else if (e.keyCode === 13) {
        this.handleBlur(e);
        return false;
      }
    };

    Autocomplete.prototype.handleClick = function(e) {
      if (e.currentTarget == null) {
        e.currentTarget = e.explicitOriginalTarget;
      }
      this.attrs.value = e.currentTarget.textContent;
      if (this.onChanged) {
        this.onChanged(this.attrs.value);
      }
      this.focus = false;
      Page.projector.scheduleRender();
      return false;
    };

    Autocomplete.prototype.handleFocus = function(e) {
      this.selected_index = 0;
      return this.focus = true;
    };

    Autocomplete.prototype.handleBlur = function(e) {
      var selected_value, values;
      selected_value = this.node.querySelector(".values .value.selected");
      if (selected_value) {
        this.setValue(selected_value.textContent);
      } else if (this.attrs.value) {
        values = this.filterValues(this.attrs.value);
        if (values.length > 0) {
          this.setValue(values[0].replace(/<.*?>/g, ""));
        } else {
          this.setValue("");
        }
      } else {
        this.setValue("");
      }
      return this.focus = false;
    };

    Autocomplete.prototype.render = function() {
      return h("div.Autocomplete", {
        "afterCreate": this.setNode
      }, [
        h("input.to", this.attrs), this.focus && this.attrs.value ? h("div.values", {
          "exitAnimation": Animation.slideUp
        }, [
          this.filterValues(this.attrs.value).map((function(_this) {
            return function(value, i) {
              return h("a.value", {
                "href": "#Select+Address",
                "key": value,
                "tabindex": "-1",
                "afterCreate": _this.renderValue,
                "onmousedown": _this.handleClick,
                "classes": {
                  "selected": _this.selected_index === i
                }
              });
            };
          })(this))
        ]) : void 0
      ]);
    };

    return Autocomplete;

  })();

  window.Autocomplete = Autocomplete;

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/utils/Class.coffee ---- */


(function() {
  var Class,
    __slice = [].slice;

  Class = (function() {
    function Class() {}

    Class.prototype.trace = true;

    Class.prototype.log = function() {
      var args;
      args = 1 <= arguments.length ? __slice.call(arguments, 0) : [];
      if (!this.trace) {
        return;
      }
      if (typeof console === 'undefined') {
        return;
      }
      args.unshift("[" + this.constructor.name + "]");
      console.log.apply(console, args);
      return this;
    };

    Class.prototype.logStart = function() {
      var args, name;
      name = arguments[0], args = 2 <= arguments.length ? __slice.call(arguments, 1) : [];
      if (!this.trace) {
        return;
      }
      this.logtimers || (this.logtimers = {});
      this.logtimers[name] = +(new Date);
      if (args.length > 0) {
        this.log.apply(this, ["" + name].concat(__slice.call(args), ["(started)"]));
      }
      return this;
    };

    Class.prototype.logEnd = function() {
      var args, ms, name;
      name = arguments[0], args = 2 <= arguments.length ? __slice.call(arguments, 1) : [];
      ms = +(new Date) - this.logtimers[name];
      this.log.apply(this, ["" + name].concat(__slice.call(args), ["(Done in " + ms + "ms)"]));
      return this;
    };

    return Class;

  })();

  window.Class = Class;

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/utils/Dollar.coffee ---- */


(function() {
  window.$ = function(selector) {
    if (selector.startsWith("#")) {
      return document.getElementById(selector.replace("#", ""));
    }
  };

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/utils/OrderManager.coffee ---- */


(function() {
  var OrderManager,
    __bind = function(fn, me){ return function(){ return fn.apply(me, arguments); }; },
    __extends = function(child, parent) { for (var key in parent) { if (__hasProp.call(parent, key)) child[key] = parent[key]; } function ctor() { this.constructor = child; } ctor.prototype = parent.prototype; child.prototype = new ctor(); child.__super__ = parent.prototype; return child; },
    __hasProp = {}.hasOwnProperty;

  OrderManager = (function(_super) {
    __extends(OrderManager, _super);

    function OrderManager() {
      this.execute = __bind(this.execute, this);
      var timer_reorder;
      timer_reorder = null;
      this.entering = {};
      this.exiting = {};
      this;
    }

    OrderManager.prototype.registerEnter = function(elem, props, cb) {
      return this.entering[props.key] = [elem, cb];
    };

    OrderManager.prototype.registerExit = function(elem, props, cb) {
      return this.exiting[props.key] = [elem, cb];
    };

    OrderManager.prototype.animateChange = function(elem, before, after) {
      var height;
      height = elem.offsetHeight;
      elem.style.width = elem.offsetWidth + "px";
      elem.style.transition = "none";
      elem.style.boxSizing = "border-box";
      elem.style.float = "left";
      elem.style.marginTop = 0 - height + "px";
      elem.style.transform = "TranslateY(" + (before - after + height) + "px)";
      setTimeout((function() {
        elem.style.transition = null;
        return elem.className += " animate-back";
      }), 1);
      return setTimeout((function() {
        elem.style.transform = "TranslateY(0px)";
        elem.style.marginTop = "0px";
        return elem.addEventListener("transitionend", function() {
          elem.classList.remove("animate-back");
          return elem.style.boxSizing = elem.style.float = elem.style.marginTop = elem.style.transform = elem.style.width = null;
        });
      }), 2);
    };

    OrderManager.prototype.execute = function(elem, projection_options, selector, properties, childs) {
      var child, child_elem, enteranim, exitanim, has_entering, has_exiting, key, moving, s, top_after, top_before, _i, _len, _ref, _ref1, _ref2, _ref3, _ref4;
      s = Date.now();
      has_entering = JSON.stringify(this.entering) !== "{}";
      has_exiting = JSON.stringify(this.exiting) !== "{}";
      if (!has_exiting && !has_entering) {
        return false;
      }
      moving = {};
      this.log(Date.now() - s);
      if (childs.length < 5000) {
        if (has_entering && has_exiting) {
          for (_i = 0, _len = childs.length; _i < _len; _i++) {
            child = childs[_i];
            key = child.properties.key;
            if (!key) {
              continue;
            }
            if (!this.entering[key]) {
              moving[key] = [child, child.domNode.offsetTop];
            }
          }
        }
      }
      this.log(Date.now() - s);
      _ref = this.exiting;
      for (key in _ref) {
        _ref1 = _ref[key], child_elem = _ref1[0], exitanim = _ref1[1];
        if (!this.entering[key]) {
          exitanim();
        } else {
          elem.removeChild(child_elem);
        }
      }
      this.log(Date.now() - s);
      _ref2 = this.entering;
      for (key in _ref2) {
        _ref3 = _ref2[key], child_elem = _ref3[0], enteranim = _ref3[1];
        if (!this.exiting[key]) {
          enteranim();
        }
      }
      this.log(Date.now() - s);
      for (key in moving) {
        _ref4 = moving[key], child = _ref4[0], top_before = _ref4[1];
        top_after = child.domNode.offsetTop;
        console.log("animateChange", top_before, top_after);
        if (top_before !== top_after) {
          this.animateChange(child.domNode, top_before, top_after);
        }
      }
      this.entering = {};
      this.exiting = {};
      return this.log(Date.now() - s, arguments);
    };

    return OrderManager;

  })(Class);

  window.OrderManager = OrderManager;

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/utils/Prototypes.coffee ---- */


(function() {
  var _base, _base1, _base2;

  if ((_base = String.prototype).startsWith == null) {
    _base.startsWith = function(s) {
      return this.slice(0, s.length) === s;
    };
  }

  if ((_base1 = String.prototype).endsWith == null) {
    _base1.endsWith = function(s) {
      return s === '' || this.slice(-s.length) === s;
    };
  }

  if ((_base2 = String.prototype).repeat == null) {
    _base2.repeat = function(count) {
      return new Array(count + 1).join(this);
    };
  }

  window.isEmpty = function(obj) {
    var key;
    for (key in obj) {
      return false;
    }
    return true;
  };

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/utils/RateLimit.coffee ---- */


(function() {
  var call_after_interval, limits;

  limits = {};

  call_after_interval = {};

  window.RateLimit = function(interval, fn) {
    if (!limits[fn]) {
      call_after_interval[fn] = false;
      fn();
      return limits[fn] = setTimeout((function() {
        if (call_after_interval[fn]) {
          fn();
        }
        delete limits[fn];
        return delete call_after_interval[fn];
      }), interval);
    } else {
      return call_after_interval[fn] = true;
    }
  };

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/utils/Text.coffee ---- */


(function() {
  var MarkedRenderer, Text,
    __extends = function(child, parent) { for (var key in parent) { if (__hasProp.call(parent, key)) child[key] = parent[key]; } function ctor() { this.constructor = child; } ctor.prototype = parent.prototype; child.prototype = new ctor(); child.__super__ = parent.prototype; return child; },
    __hasProp = {}.hasOwnProperty;

  MarkedRenderer = (function(_super) {
    __extends(MarkedRenderer, _super);

    function MarkedRenderer() {
      return MarkedRenderer.__super__.constructor.apply(this, arguments);
    }

    MarkedRenderer.prototype.image = function(href, title, text) {
      return "<code>![" + text + "](" + href + ")</code>";
    };

    return MarkedRenderer;

  })(marked.Renderer);

  Text = (function() {
    function Text() {}

    Text.prototype.toColor = function(text) {
      var hash, i, _i, _ref;
      hash = 0;
      for (i = _i = 0, _ref = text.length - 1; 0 <= _ref ? _i <= _ref : _i >= _ref; i = 0 <= _ref ? ++_i : --_i) {
        hash += text.charCodeAt(i) * i;
        hash = hash % 1000;
      }
      return "hsl(" + (hash % 360) + ",30%,50%)";
    };

    Text.prototype.renderMarked = function(text, options) {
      if (options == null) {
        options = {};
      }
      options["gfm"] = true;
      options["breaks"] = true;
      options["renderer"] = marked_renderer;
      text = this.fixReply(text);
      text = marked(text, options);
      text = this.emailLinks(text);
      return this.fixHtmlLinks(text);
    };

    Text.prototype.emailLinks = function(text) {
      return text.replace(/([a-zA-Z0-9]+)@zeroid.bit/g, "<a href='?to=$1' onclick='return Page.message_create.show(\"$1\")'>$1@zeroid.bit</a>");
    };

    Text.prototype.fixHtmlLinks = function(text) {
      if (window.is_proxy) {
        return text.replace(/href="http:\/\/(127.0.0.1|localhost):43110/g, 'href="http://zero');
      } else {
        return text.replace(/href="http:\/\/(127.0.0.1|localhost):43110/g, 'href="');
      }
    };

    Text.prototype.fixLink = function(link) {
      if (window.is_proxy) {
        return link.replace(/http:\/\/(127.0.0.1|localhost):43110/, 'http://zero');
      } else {
        return link.replace(/http:\/\/(127.0.0.1|localhost):43110/, '');
      }
    };

    Text.prototype.toUrl = function(text) {
      return text.replace(/[^A-Za-z0-9]/g, "+").replace(/[+]+/g, "+").replace(/[+]+$/, "");
    };

    Text.prototype.fixReply = function(text) {
      return text.replace(/(>.*\n)([^\n>])/gm, "$1\n$2");
    };

    Text.prototype.toBitcoinAddress = function(text) {
      return text.replace(/[^A-Za-z0-9]/g, "");
    };

    Text.prototype.jsonEncode = function(obj) {
      return unescape(encodeURIComponent(JSON.stringify(obj)));
    };

    Text.prototype.jsonDecode = function(obj) {
      return JSON.parse(decodeURIComponent(escape(obj)));
    };

    Text.prototype.fileEncode = function(obj) {
      if (typeof obj === "string") {
        return btoa(unescape(encodeURIComponent(obj)));
      } else {
        return btoa(unescape(encodeURIComponent(JSON.stringify(obj, void 0, '\t'))));
      }
    };

    Text.prototype.utf8Encode = function(s) {
      return unescape(encodeURIComponent(s));
    };

    Text.prototype.utf8Decode = function(s) {
      return decodeURIComponent(escape(s));
    };

    Text.prototype.distance = function(s1, s2) {
      var char, extra_parts, key, match, next_find, next_find_i, val, _i, _len;
      s1 = s1.toLocaleLowerCase();
      s2 = s2.toLocaleLowerCase();
      next_find_i = 0;
      next_find = s2[0];
      match = true;
      extra_parts = {};
      for (_i = 0, _len = s1.length; _i < _len; _i++) {
        char = s1[_i];
        if (char !== next_find) {
          if (extra_parts[next_find_i]) {
            extra_parts[next_find_i] += char;
          } else {
            extra_parts[next_find_i] = char;
          }
        } else {
          next_find_i++;
          next_find = s2[next_find_i];
        }
      }
      if (extra_parts[next_find_i]) {
        extra_parts[next_find_i] = "";
      }
      extra_parts = (function() {
        var _results;
        _results = [];
        for (key in extra_parts) {
          val = extra_parts[key];
          _results.push(val);
        }
        return _results;
      })();
      if (next_find_i >= s2.length) {
        return extra_parts.length + extra_parts.join("").length;
      } else {
        return false;
      }
    };

    Text.prototype.parseQuery = function(query) {
      var key, params, part, parts, val, _i, _len, _ref;
      params = {};
      parts = query.split('&');
      for (_i = 0, _len = parts.length; _i < _len; _i++) {
        part = parts[_i];
        _ref = part.split("="), key = _ref[0], val = _ref[1];
        if (val) {
          params[decodeURIComponent(key)] = decodeURIComponent(val);
        } else {
          params["url"] = decodeURIComponent(key);
        }
      }
      return params;
    };

    Text.prototype.encodeQuery = function(params) {
      var back, key, val;
      back = [];
      if (params.url) {
        back.push(params.url);
      }
      for (key in params) {
        val = params[key];
        if (!val || key === "url") {
          continue;
        }
        back.push((encodeURIComponent(key)) + "=" + (encodeURIComponent(val)));
      }
      return back.join("&");
    };

    return Text;

  })();

  window.is_proxy = window.location.pathname === "/";

  window.marked_renderer = new MarkedRenderer();

  window.Text = new Text();

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/utils/Time.coffee ---- */


(function() {
  var Time;

  Time = (function() {
    function Time() {}

    Time.prototype.since = function(timestamp) {
      var back, now, secs;
      now = +(new Date) / 1000;
      if (timestamp > 1000000000000) {
        timestamp = timestamp / 1000;
      }
      secs = now - timestamp;
      if (secs < 60) {
        back = "Just now";
      } else if (secs < 60 * 60) {
        back = (Math.round(secs / 60)) + " minutes ago";
      } else if (secs < 60 * 60 * 24) {
        back = (Math.round(secs / 60 / 60)) + " hours ago";
      } else if (secs < 60 * 60 * 24 * 3) {
        back = (Math.round(secs / 60 / 60 / 24)) + " days ago";
      } else {
        back = "on " + this.date(timestamp);
      }
      back = back.replace(/1 ([a-z]+)s/, "1 $1");
      return back;
    };

    Time.prototype.date = function(timestamp, format) {
      var display, parts;
      if (format == null) {
        format = "short";
      }
      if (timestamp > 1000000000000) {
        timestamp = timestamp / 1000;
      }
      parts = (new Date(timestamp * 1000)).toString().split(" ");
      if (format === "short") {
        display = parts.slice(1, 4);
      } else {
        display = parts.slice(1, 5);
      }
      return display.join(" ").replace(/( [0-9]{4})/, ",$1");
    };

    Time.prototype.timestamp = function(date) {
      if (date == null) {
        date = "";
      }
      if (date === "now" || date === "") {
        return parseInt(+(new Date) / 1000);
      } else {
        return parseInt(Date.parse(date) / 1000);
      }
    };

    return Time;

  })();

  window.Time = new Time;

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/utils/ZeroFrame.coffee ---- */


(function() {
  var ZeroFrame,
    __bind = function(fn, me){ return function(){ return fn.apply(me, arguments); }; },
    __extends = function(child, parent) { for (var key in parent) { if (__hasProp.call(parent, key)) child[key] = parent[key]; } function ctor() { this.constructor = child; } ctor.prototype = parent.prototype; child.prototype = new ctor(); child.__super__ = parent.prototype; return child; },
    __hasProp = {}.hasOwnProperty;

  ZeroFrame = (function(_super) {
    __extends(ZeroFrame, _super);

    function ZeroFrame(url) {
      var wrapper_nonce_match;
      this.onCloseWebsocket = __bind(this.onCloseWebsocket, this);
      this.onOpenWebsocket = __bind(this.onOpenWebsocket, this);
      this.onRequest = __bind(this.onRequest, this);
      this.onMessage = __bind(this.onMessage, this);
      this.url = url;
      this.waiting_cb = {};
      // Local-identity fork: this stack's own wrapper (P2P/Ui/Wrapper.py)
      // validates every postMessage from a site iframe against a
      // wrapper_nonce embedded in that iframe's own URL (see
      // media/template/js/ZeroFrame.js, this port's own reference
      // implementation) -- real ZeroMail's original ZeroFrame.coffee
      // predates that check entirely and never sent one, so every one
      // of its messages was silently rejected ("Message nonce error"),
      // leaving Page.site_info permanently null. Found live: driving
      // this exact fork through a real browser was what surfaced it --
      // nothing in this file's own automated tests exercises the
      // wrapper's postMessage validation at all.
      wrapper_nonce_match = (document.location.href.match(/wrapper_nonce=([A-Za-z0-9]+)/) || []);
      this.wrapper_nonce = wrapper_nonce_match[1] || "";
      this.connect();
      this.next_message_id = 1;
      this.init();
    }

    ZeroFrame.prototype.init = function() {
      return this;
    };

    ZeroFrame.prototype.connect = function() {
      this.target = window.parent;
      window.addEventListener("message", this.onMessage, false);
      return this.cmd("innerReady");
    };

    ZeroFrame.prototype.onMessage = function(e) {
      var cmd, message;
      message = e.data;
      cmd = message.cmd;
      if (cmd === "response") {
        if (this.waiting_cb[message.to] != null) {
          return this.waiting_cb[message.to](message.result);
        } else {
          return this.log("Websocket callback not found:", message);
        }
      } else if (cmd === "wrapperReady") {
        return this.cmd("innerReady");
      } else if (cmd === "ping") {
        return this.response(message.id, "pong");
      } else if (cmd === "wrapperOpenedWebsocket") {
        return this.onOpenWebsocket();
      } else if (cmd === "wrapperClosedWebsocket") {
        return this.onCloseWebsocket();
      } else {
        return this.onRequest(cmd, message.params);
      }
    };

    ZeroFrame.prototype.onRequest = function(cmd, message) {
      return this.log("Unknown request", message);
    };

    ZeroFrame.prototype.response = function(to, result) {
      return this.send({
        "cmd": "response",
        "to": to,
        "result": result
      });
    };

    ZeroFrame.prototype.cmd = function(cmd, params, cb) {
      if (params == null) {
        params = {};
      }
      if (cb == null) {
        cb = null;
      }
      return this.send({
        "cmd": cmd,
        "params": params
      }, cb);
    };

    ZeroFrame.prototype.send = function(message, cb) {
      if (cb == null) {
        cb = null;
      }
      message.wrapper_nonce = this.wrapper_nonce;
      message.id = this.next_message_id;
      this.next_message_id += 1;
      this.target.postMessage(message, "*");
      if (cb) {
        return this.waiting_cb[message.id] = cb;
      }
    };

    ZeroFrame.prototype.onOpenWebsocket = function() {
      return this.log("Websocket open");
    };

    ZeroFrame.prototype.onCloseWebsocket = function() {
      return this.log("Websocket close");
    };

    return ZeroFrame;

  })(Class);

  window.ZeroFrame = ZeroFrame;

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/Leftbar.coffee ---- */


(function() {
  var Leftbar,
    __bind = function(fn, me){ return function(){ return fn.apply(me, arguments); }; },
    __extends = function(child, parent) { for (var key in parent) { if (__hasProp.call(parent, key)) child[key] = parent[key]; } function ctor() { this.constructor = child; } ctor.prototype = parent.prototype; child.prototype = new ctor(); child.__super__ = parent.prototype; return child; },
    __hasProp = {}.hasOwnProperty,
    __indexOf = [].indexOf || function(item) { for (var i = 0, l = this.length; i < l; i++) { if (i in this && this[i] === item) return i; } return -1; };

  Leftbar = (function(_super) {
    __extends(Leftbar, _super);

    function Leftbar() {
      this.render = __bind(this.render, this);
      this.handleLogoutClick = __bind(this.handleLogoutClick, this);
      this.handleFolderClick = __bind(this.handleFolderClick, this);
      this.handleNewMessageClick = __bind(this.handleNewMessageClick, this);
      this.handleContactClick = __bind(this.handleContactClick, this);
      this.contacts = [];
      this.folder_active = "inbox";
      this.reload_contacts = true;
      this;
    }

    Leftbar.prototype.handleContactClick = function(e) {
      Page.message_create.show(e.currentTarget.querySelector(".name").textContent);
      return false;
    };

    Leftbar.prototype.handleNewMessageClick = function(e) {
      Page.message_create.show();
      return false;
    };

    Leftbar.prototype.handleFolderClick = function(e) {
      var folder_name;
      folder_name = e.currentTarget.href.replace(/.*\?/, "");
      this.folder_active = folder_name.toLowerCase();
      Page.message_lists.setActive(this.folder_active);
      Page.cmd("wrapperReplaceState", [{}, "", folder_name]);
      return false;
    };

    Leftbar.prototype.handleLogoutClick = function(e) {
      Page.cmd("certSelect", [[window.ZEROMAIL_LOCAL_DOMAIN || "local"]]);
      Page.local_storage = {};
      Page.saveLocalStorage(function() {
        return Page.getLocalStorage();
      });
      return false;
    };

    Leftbar.prototype.loadContacts = function(cb) {
      var address, addresses;
      addresses = (function() {
        var _results;
        _results = [];
        for (address in Page.local_storage.parsed.my_secret) {
          _results.push(address);
        }
        return _results;
      })();
      return Page.users.getUsernames(addresses, function(rows) {
        var auth_address, cert_user_id, contacts;
        contacts = (function() {
          var _results;
          _results = [];
          for (auth_address in rows) {
            cert_user_id = rows[auth_address];
            _results.push([cert_user_id, auth_address]);
          }
          return _results;
        })();
        return cb(contacts);
      });
    };

    Leftbar.prototype.getContacts = function() {
      if (this.reload_contacts) {
        this.reload_contacts = false;
        this.log("Reloading contacts");
        Page.on_local_storage.then((function(_this) {
          return function() {
            var address, known_addresses, unknown_addresses, username;
            known_addresses = (function() {
              var _i, _len, _ref, _ref1, _results;
              _ref = this.contacts;
              _results = [];
              for (_i = 0, _len = _ref.length; _i < _len; _i++) {
                _ref1 = _ref[_i], username = _ref1[0], address = _ref1[1];
                _results.push(address);
              }
              return _results;
            }).call(_this);
            unknown_addresses = (function() {
              var _results;
              _results = [];
              for (address in Page.local_storage.parsed.my_secret) {
                if (__indexOf.call(known_addresses, address) < 0) {
                  _results.push(address);
                }
              }
              return _results;
            })();
            if (unknown_addresses.length > 0) {
              return _this.loadContacts(function(contacts) {
                _this.log("Unknown contacts found, reloaded.");
                contacts = contacts.sort();
                _this.contacts = contacts;
                return Page.projector.scheduleRender();
              });
            }
          };
        })(this));
      }
      return this.contacts;
    };

    Leftbar.prototype.render = function() {
      var contacts, _ref, _ref1;
      contacts = ((_ref = Page.site_info) != null ? _ref.cert_user_id : void 0) ? this.getContacts() : [];
      return h("div.Leftbar", [
        h("a.logo", {
          href: "?Main"
        }, ["ZeroMail_"]), h("a.button-create.newmessage", {
          href: "#New+message",
          onclick: this.handleNewMessageClick
        }, ["New message"]), h("div.folders", [
          h("a", {
            key: "Inbox",
            href: "?Inbox",
            classes: {
              "active": Page.message_lists.active === Page.message_lists.inbox
            },
            onclick: this.handleFolderClick
          }, ["Inbox"]), h("a", {
            key: "Sent",
            href: "?Sent",
            classes: {
              "active": Page.message_lists.active === Page.message_lists.sent
            },
            onclick: this.handleFolderClick
          }, ["Sent", h("span.quota", Page.user.formatQuota())])
        ]), contacts.length > 0 ? [
          h("h2", ["Contacts"]), h("div.contacts-wrapper", [
            h("div.contacts", contacts.map((function(_this) {
              return function(_arg) {
                var address, username;
                username = _arg[0], address = _arg[1];
                return h("a.username", {
                  key: username,
                  href: Page.createUrl("to", username.replace("@zeroid.bit", "")),
                  onclick: _this.handleContactClick,
                  "enterAnimation": Animation.show
                }, [
                  h("span.bullet", {
                    "style": "color: " + (Text.toColor(address))
                  }, ["•"]), h("span.name", [username.replace("@zeroid.bit", "")])
                ]);
              };
            })(this)))
          ])
        ] : void 0, ((_ref1 = Page.site_info) != null ? _ref1.cert_user_id : void 0) ? h("a.logout.icon.icon-logout", {
          href: "?Logout",
          title: "Logout",
          onclick: this.handleLogoutClick
        }) : void 0
      ]);
    };

    Leftbar.prototype.onSiteInfo = function(site_info) {
      var action, inner_path, _ref;
      if (site_info.event) {
        _ref = site_info.event, action = _ref[0], inner_path = _ref[1];
        if (action === "file_done" && inner_path.endsWith("data.json")) {
          return this.reload_contacts = true;
        }
      }
    };

    return Leftbar;

  })(Class);

  window.Leftbar = Leftbar;

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/Message.coffee ---- */


(function() {
  var Message,
    __bind = function(fn, me){ return function(){ return fn.apply(me, arguments); }; };

  Message = (function() {
    function Message(_at_message_list, _at_row) {
      this.message_list = _at_message_list;
      this.row = _at_row;
      this.renderShow = __bind(this.renderShow, this);
      this.renderUsername = __bind(this.renderUsername, this);
      this.renderUsernameLink = __bind(this.renderUsernameLink, this);
      this.handleContactClick = __bind(this.handleContactClick, this);
      this.renderBodyPreview = __bind(this.renderBodyPreview, this);
      this.renderBody = __bind(this.renderBody, this);
      this.handleReplyClick = __bind(this.handleReplyClick, this);
      this.handleDeleteClick = __bind(this.handleDeleteClick, this);
      this.handleListClick = __bind(this.handleListClick, this);
      this.active = false;
      this.selected = false;
      this.deleted = false;
      this.key = this.row.key;
      if (this.row.folder === "sent" || Page.local_storage.read[this.row.date_added]) {
        this.read = true;
      } else {
        this.read = false;
      }
      this;
    }

    Message.prototype.getBodyPreview = function() {
      return this.row.body.slice(0, 81);
    };

    Message.prototype.markRead = function(read) {
      if (read == null) {
        read = true;
      }
      if (!this.read) {
        Page.local_storage.read[this.row.date_added] = true;
        Page.saveLocalStorage();
      }
      return this.read = read;
    };

    Message.prototype.handleListClick = function(e) {
      var active_index, message, my_index, _i, _len, _ref;
      this.markRead();
      if (e && e.ctrlKey) {
        this.selected = !this.selected;
        if (this.message_list.message_lists.message_active) {
          this.message_list.message_lists.message_active.active = false;
          this.message_list.message_lists.message_active.selected = true;
          this.message_list.message_lists.message_active = null;
          Page.message_show.message = null;
        }
        this.message_list.updateSelected();
      } else if (e && e.shiftKey) {
        if (this.message_list.message_lists.message_active) {
          active_index = this.message_list.messages.indexOf(this.message_list.message_lists.message_active);
          my_index = this.message_list.messages.indexOf(this);
          _ref = this.message_list.messages.slice(Math.min(active_index, my_index), +Math.max(active_index, my_index) + 1 || 9e9);
          for (_i = 0, _len = _ref.length; _i < _len; _i++) {
            message = _ref[_i];
            message.selected = true;
          }
        }
        this.message_list.updateSelected();
      } else {
        this.message_list.setActiveMessage(this);
        Page.message_show.setMessage(this);
      }
      return false;
    };

    Message.prototype.handleDeleteClick = function() {
      this.message_list.deleteMessage(this);
      this.message_list.save();
      return false;
    };

    Message.prototype.handleReplyClick = function() {
      Page.message_create.setReplyDetails();
      Page.message_create.show();
      return false;
    };

    Message.prototype.renderBody = function(node) {
      return node.innerHTML = Text.renderMarked(this.row.body, {
        "sanitize": true
      });
    };

    Message.prototype.renderBodyPreview = function(node) {
      return node.textContent = this.getBodyPreview();
    };

    Message.prototype.handleContactClick = function(e) {
      Page.message_create.show(e.currentTarget.querySelector(".name").textContent);
      return false;
    };

    Message.prototype.renderUsernameLink = function(username, address) {
      var color;
      color = Text.toColor(address);
      if (username == null) {
        username = "n/a";
      }
      if (username == null) {
        username = "address";
      }
      return h("a.username", {
        href: Page.createUrl("to", username.replace("@zeroid.bit", "")),
        onclick: this.handleContactClick
      }, this.renderUsername(username, address));
    };

    Message.prototype.renderUsername = function(username, address) {
      var color;
      color = Text.toColor(address);
      return [
        h("span.name", {
          "title": address,
          "style": "color: " + color
        }, [username.replace("@zeroid.bit", "")])
      ];
    };

    Message.prototype.renderList = function() {
      return h("a.Message", {
        "key": this.key,
        "href": "#MessageShow:" + this.row.key,
        "onclick": this.handleListClick,
        "disableAnimation": this.row.disable_animation,
        "enterAnimation": Animation.slideDown,
        "exitAnimation": Animation.slideUp,
        classes: {
          "active": this.active,
          "selected": this.selected,
          "unread": !this.read
        }
      }, [
        h("div.sent", [Time.since(this.row.date_added)]), h("div.subject", [this.row.subject]), this.row.folder === "sent" ? h("div.to.username", ["To: ", this.renderUsername(this.row.to, this.row.to_address)]) : h("div.from.username", ["From: ", this.renderUsername(this.row.from, this.row.from_address)]), h("div.preview", {
          "afterCreate": this.renderBodyPreview,
          "updateAnimation": this.renderBodyPreview
        }, [this.row.body])
      ]);
    };

    Message.prototype.renderShow = function() {
      return h("div.Message", {
        "key": this.key,
        "enterAnimation": Animation.show,
        "classes": {
          "deleted": this.deleted
        }
      }, [
        h("div.tools", [
          h("a.icon.icon-reply", {
            href: "#Reply",
            "title": "Reply message",
            onclick: this.handleReplyClick
          }), h("a.icon.icon-trash", {
            href: "#Delete",
            "title": "Delete message",
            onclick: this.handleDeleteClick
          })
        ]), h("div.subject", [this.row.subject]), h("div.sent", [Time.date(this.row.date_added, "full")]), this.row.folder === "sent" ? h("div.to.username", ["To: ", this.renderUsernameLink(this.row.to, this.row.to_address)]) : h("div.from.username", ["From: ", this.renderUsernameLink(this.row.from, this.row.from_address)]), h("div.body", {
          "afterCreate": this.renderBody,
          "updateAnimation": this.renderBody
        }, [this.row.body])
      ]);
    };

    return Message;

  })();

  window.Message = Message;

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/MessageCreate.coffee ---- */


(function() {
  var MessageCreate,
    __bind = function(fn, me){ return function(){ return fn.apply(me, arguments); }; },
    __extends = function(child, parent) { for (var key in parent) { if (__hasProp.call(parent, key)) child[key] = parent[key]; } function ctor() { this.constructor = child; } ctor.prototype = parent.prototype; child.prototype = new ctor(); child.__super__ = parent.prototype; return child; },
    __hasProp = {}.hasOwnProperty;

  MessageCreate = (function(_super) {
    __extends(MessageCreate, _super);

    function MessageCreate() {
      this.render = __bind(this.render, this);
      this.handleSendClick = __bind(this.handleSendClick, this);
      this.handleInput = __bind(this.handleInput, this);
      this.handleCloseClick = __bind(this.handleCloseClick, this);
      this.handleTitleClick = __bind(this.handleTitleClick, this);
      this.hide = __bind(this.hide, this);
      this.show = __bind(this.show, this);
      this.getTitle = __bind(this.getTitle, this);
      this.getUsernames = __bind(this.getUsernames, this);
      this.setReplyDetails = __bind(this.setReplyDetails, this);
      this.setNode = __bind(this.setNode, this);
      this.isFilled = __bind(this.isFilled, this);
      this.isEmpty = __bind(this.isEmpty, this);
      this.subject = "";
      this.body = "";
      this.minimized = true;
      this.sending = false;
      this.just_sent = false;
      this.user_address = {};
      this.update_usernames = true;
      this.field_to = new Autocomplete(this.getUsernames, {
        type: "text",
        placeholder: "Username",
        value: ""
      });
      this.node = null;
    }

    MessageCreate.property('to', {
      get: function() {
        return this.field_to.attrs.value;
      },
      set: function(to) {
        return this.field_to.setValue(to);
      }
    });

    MessageCreate.prototype.isEmpty = function() {
      return !(this.body + this.subject + this.to);
    };

    MessageCreate.prototype.isFilled = function() {
      return this.body !== "" && this.subject !== "" && this.to !== "" && Page.user.publickey;
    };

    MessageCreate.prototype.setNode = function(node) {
      return this.node = node;
    };

    MessageCreate.prototype.setReplyDetails = function() {
      var current_message;
      current_message = Page.message_lists.message_active;
      if (current_message.row.folder === "sent") {
        this.to = current_message.row.to.replace("@zeroid.bit", "");
      } else {
        this.to = current_message.row.from.replace("@zeroid.bit", "");
      }
      return this.subject = "Re: " + current_message.row.subject.replace("Re: ", "");
    };

    MessageCreate.prototype.getUsernames = function() {
      var address, username;
      return (function() {
        var _ref, _results;
        _ref = this.user_address;
        _results = [];
        for (username in _ref) {
          address = _ref[username];
          _results.push(username.replace("@zeroid.bit", ""));
        }
        return _results;
      }).call(this);
    };

    MessageCreate.prototype.getTitle = function() {
      var title;
      if (this.just_sent) {
        title = "Message sent!";
      } else if (this.isEmpty()) {
        if (Page.message_lists.message_active) {
          title = "Reply to this message";
        } else {
          title = "New message";
        }
      } else {
        if (this.subject.startsWith("Re:")) {
          title = "Reply to message";
        } else {
          title = "New message";
        }
      }
      return title;
    };

    MessageCreate.prototype.updateUsernames = function() {
      this.update_usernames = false;
      return Page.users.getAll((function(_this) {
        return function(user_address) {
          return _this.user_address = user_address;
        };
      })(this));
    };

    MessageCreate.prototype.show = function(to, subject, body) {
      if (to) {
        this.to = to;
      }
      if (subject) {
        this.subject = subject;
      }
      if (body) {
        this.body = body;
      }
      this.minimized = false;
      document.body.classList.add("MessageCreate-opened");
      if (!this.to) {
        this.node.querySelector(".to").focus();
      } else if (!this.subject) {
        this.node.querySelector(".subject").focus();
      } else if (!this.body) {
        this.node.querySelector(".body").focus();
      }
      if (this.update_usernames) {
        this.updateUsernames();
      }
      return false;
    };

    MessageCreate.prototype.hide = function() {
      document.body.classList.remove("MessageCreate-opened");
      return this.minimized = true;
    };

    MessageCreate.prototype.handleTitleClick = function(e) {
      e.cancelBubble = true;
      if (this.minimized) {
        if (this.isEmpty() && Page.message_lists.message_active) {
          this.setReplyDetails();
        }
        this.show();
      } else {
        this.hide();
      }
      return false;
    };

    MessageCreate.prototype.handleCloseClick = function(e) {
      e.cancelBubble = true;
      this.hide();
      this.to = "";
      this.subject = "";
      this.body = "";
      return false;
    };

    MessageCreate.prototype.handleInput = function(e) {
      this[e.target.name] = e.target.value;
      return false;
    };

    MessageCreate.prototype.handleSendClick = function(e) {
      var to;
      to = this.to;
      if (to.indexOf("@") === -1) {
        to += "@zeroid.bit";
      }
      if (!this.user_address[to]) {
        to = "";
        this.node.querySelector(".to").focus();
        return false;
      }
      Animation.scramble(this.node.querySelector(".to"));
      Animation.scramble(this.node.querySelector(".subject"));
      Animation.scramble(this.node.querySelector(".body"));
      this.sending = true;
      this.log("Sending message", to, this.user_address[to]);
      Page.user.getSecret(this.user_address[to], (function(_this) {
        return function(aes_key) {
          var message;
          if (!aes_key) {
            _this.sending = false;
            return false;
          }
          message = {
            "subject": _this.subject,
            "body": _this.body,
            "to": to
          };
          _this.log("Encrypting to", aes_key);
          return Page.cmd("aesEncrypt", [Text.jsonEncode(message), aes_key], function(res) {
            var encrypted, iv;
            aes_key = res[0], iv = res[1], encrypted = res[2];
            Page.user.data.message[Page.user.getNewIndex("message")] = iv + "," + encrypted;
            return Page.user.saveData().then(function(send_res) {
              _this.sending = false;
              if (send_res) {
                _this.hide();
                _this.just_sent = true;
                if (_this.user_address[message.to] === Page.site_info.auth_address) {
                  _this.log("Sent message to myself, reload inbox");
                  Page.message_lists.inbox.reload = true;
                }
                return setTimeout((function() {
                  _this.just_sent = false;
                  _this.to = "";
                  _this.subject = "";
                  _this.body = "";
                  Page.leftbar.reload_contacts = true;
                  return Page.projector.scheduleRender();
                }), 4000);
              } else {
                _this.node.querySelector(".to").value = _this.to;
                _this.node.querySelector(".subject").value = _this.subject;
                return _this.node.querySelector(".body").value = _this.body;
              }
            });
          });
        };
      })(this));
      return false;
    };

    MessageCreate.prototype.render = function() {
      return h("div.MessageCreate", {
        classes: {
          minimized: this.minimized,
          empty: this.isEmpty(),
          sent: this.just_sent
        },
        afterCreate: this.setNode
      }, [
        h("a.titlebar", {
          "href": "#New+message",
          onclick: this.handleTitleClick
        }, [
          h("span.text", [this.getTitle()]), h("span.buttons", [
            h("a.minimize", {
              href: "#Minimize",
              onclick: this.handleTitleClick
            }, ["_"]), h("a.close", {
              href: "#Close",
              onclick: this.handleCloseClick
            }, ["×"])
          ])
        ]), h("label.label-to", ["To:"]), this.field_to.render(), h("input.subject", {
          type: "text",
          placeholder: "Subject",
          name: "subject",
          value: this.subject,
          oninput: this.handleInput
        }), h("textarea.body", {
          placeholder: "Message",
          name: "body",
          value: this.body,
          oninput: this.handleInput
        }), h("a.button.button-submit.button-send", {
          href: "#Send",
          classes: {
            "disabled": !this.isFilled(),
            "loading": this.sending || this.just_sent
          },
          onclick: this.handleSendClick
        }, ["Encrypt & Send message"])
      ]);
    };

    MessageCreate.prototype.onSiteInfo = function(site_info) {
      var _ref;
      if (((_ref = site_info.event) != null ? _ref[0] : void 0) === "file_done") {
        return this.update_usernames = true;
      }
    };

    return MessageCreate;

  })(Class);

  window.MessageCreate = MessageCreate;

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/MessageList.coffee ---- */


(function() {
  var MessageList,
    __bind = function(fn, me){ return function(){ return fn.apply(me, arguments); }; },
    __extends = function(child, parent) { for (var key in parent) { if (__hasProp.call(parent, key)) child[key] = parent[key]; } function ctor() { this.constructor = child; } ctor.prototype = parent.prototype; child.prototype = new ctor(); child.__super__ = parent.prototype; return child; },
    __hasProp = {}.hasOwnProperty;

  MessageList = (function(_super) {
    __extends(MessageList, _super);

    function MessageList(_at_message_lists) {
      this.message_lists = _at_message_lists;
      this.render = __bind(this.render, this);
      this.handleMoreClick = __bind(this.handleMoreClick, this);
      this.title = "Unknown";
      this.loading = false;
      this.loaded = false;
      this.has_more = false;
      this.loading_message = "Loading...";
      this.messages = [];
      this.selected = [];
      this.message_db = {};
    }

    MessageList.prototype.getMessages = function() {
      return this.messages;
    };

    MessageList.prototype.setActiveMessage = function(message) {
      if (this.message_lists.message_active) {
        this.message_lists.message_active.active = false;
      }
      message.active = true;
      this.message_lists.message_active = message;
      return this.deselectMessages();
    };

    MessageList.prototype.deselectMessages = function() {
      var message, _i, _len, _ref;
      _ref = this.selected;
      for (_i = 0, _len = _ref.length; _i < _len; _i++) {
        message = _ref[_i];
        message.selected = false;
      }
      return this.updateSelected();
    };

    MessageList.prototype.updateSelected = function() {
      var message;
      return this.selected = (function() {
        var _i, _len, _ref, _results;
        _ref = this.messages;
        _results = [];
        for (_i = 0, _len = _ref.length; _i < _len; _i++) {
          message = _ref[_i];
          if (message.selected) {
            _results.push(message);
          }
        }
        return _results;
      }).call(this);
    };

    MessageList.prototype.addMessage = function(message_row, index) {
      var message;
      if (index == null) {
        index = -1;
      }
      message = new Message(this, message_row);
      this.message_db[message_row.key] = message;
      if (index >= 0) {
        this.messages.splice(index, 0, message);
      } else {
        this.messages.push(message);
      }
      return message;
    };

    MessageList.prototype.deleteMessage = function(message) {
      var index;
      message.deleted = true;
      index = this.messages.indexOf(message);
      if (index > -1) {
        return this.messages.splice(index, 1);
      }
    };

    MessageList.prototype.syncMessages = function(message_rows) {
      var current_obj, last_obj, message_row, _i, _len, _results;
      last_obj = null;
      _results = [];
      for (_i = 0, _len = message_rows.length; _i < _len; _i++) {
        message_row = message_rows[_i];
        current_obj = this.message_db[message_row.key];
        if (current_obj) {
          current_obj.row = message_row;
          _results.push(last_obj = current_obj);
        } else {
          if (last_obj) {
            _results.push(last_obj = this.addMessage(message_row, this.messages.indexOf(last_obj) + 1));
          } else {
            _results.push(last_obj = this.addMessage(message_row, 0));
          }
        }
      }
      return _results;
    };

    MessageList.prototype.setLoadingMessage = function(_at_loading_message) {
      this.loading_message = _at_loading_message;
      return Page.projector.scheduleRender();
    };

    MessageList.prototype.handleMoreClick = function() {
      this.reload = true;
      this.getMessages("nolimit");
      return false;
    };

    MessageList.prototype.render = function() {
      var messages, _ref;
      messages = ((_ref = Page.site_info) != null ? _ref.cert_user_id : void 0) ? this.getMessages() : [];
      if (messages.length > 0) {
        return h("div.MessageList", {
          "key": this.title,
          "enterAnimation": Animation.show
        }, messages.map(function(message) {
          return message.renderList();
        }), h("a.more", {
          href: "#More",
          classes: {
            "visible": this.has_more,
            "loading": this.loading
          },
          onclick: this.handleMoreClick
        }, "Load more messages"));
      } else if (this.loading) {
        return h("div.MessageList.empty", {
          "key": this.title + ".loading",
          "enterAnimation": Animation.show,
          "afterCreate": Animation.show,
          "delay": 1
        }, [this.title + ": " + this.loading_message, h("span.cursor", ["_"])]);
      } else {
        return h("div.MessageList.empty", {
          "key": this.title + ".empty",
          "enterAnimation": Animation.show,
          "afterCreate": Animation.show,
          "delay": 0.5
        }, [this.title + ": No messages", h("span.cursor", ["_"])]);
      }
    };

    return MessageList;

  })(Class);

  window.MessageList = MessageList;

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/MessageListInbox.coffee ---- */


(function() {
  var MessageListInbox,
    __extends = function(child, parent) { for (var key in parent) { if (__hasProp.call(parent, key)) child[key] = parent[key]; } function ctor() { this.constructor = child; } ctor.prototype = parent.prototype; child.prototype = new ctor(); child.__super__ = parent.prototype; return child; },
    __hasProp = {}.hasOwnProperty,
    __indexOf = [].indexOf || function(item) { for (var i = 0, l = this.length; i < l; i++) { if (i in this && this[i] === item) return i; } return -1; };

  MessageListInbox = (function(_super) {
    __extends(MessageListInbox, _super);

    function MessageListInbox() {
      MessageListInbox.__super__.constructor.apply(this, arguments);
      this.reload = true;
      this.loading = false;
      this.loading_message = "Loading...";
      this.nolimit_loaded = false;
      this.messages = [];
      this.my_aes_keys = {};
      this.title = "Inbox";
    }

    MessageListInbox.prototype.getParsedDb = function(cb) {
      return Page.on_local_storage.then((function(_this) {
        return function() {
          return cb(Page.local_storage.parsed);
        };
      })(this));
    };

    MessageListInbox.prototype.decryptKnownAesKeys = function(parsed_db, cb) {
      var dates, directories, load_keys, query, secret_id, user_address, where;
      load_keys = ((function() {
        var _ref, _results;
        if (!this.my_aes_keys[user_address]) {
          _ref = parsed_db.my_secret;
          _results = [];
          for (user_address in _ref) {
            secret_id = _ref[user_address];
            _results.push([user_address, secret_id]);
          }
          return _results;
        }
      }).call(this));
      if (load_keys.length > 0) {
        this.log("Loading keys", load_keys.length);
        directories = (function() {
          var _i, _len, _ref, _results;
          _results = [];
          for (_i = 0, _len = load_keys.length; _i < _len; _i++) {
            _ref = load_keys[_i], user_address = _ref[0], secret_id = _ref[1];
            _results.push("'" + user_address + "'");
          }
          return _results;
        })();
        dates = (function() {
          var _i, _len, _ref, _results;
          _results = [];
          for (_i = 0, _len = load_keys.length; _i < _len; _i++) {
            _ref = load_keys[_i], user_address = _ref[0], secret_id = _ref[1];
            _results.push(parseInt(secret_id));
          }
          return _results;
        })();
        where = "directory IN (" + (directories.join(',')) + ") AND date_added IN (" + (dates.join(',')) + ")";
        query = "SELECT * FROM secret LEFT JOIN json USING (json_id) WHERE " + where;
        return Page.cmd("dbQuery", query, (function(_this) {
          return function(rows) {
            var row;
            return Page.cmd("eciesDecrypt", [
              (function() {
                var _i, _len, _results;
                _results = [];
                for (_i = 0, _len = rows.length; _i < _len; _i++) {
                  row = rows[_i];
                  _results.push(row.encrypted);
                }
                return _results;
              })()
            ], function(decrypted_keys) {
              var decrypted_key, i, _i, _len;
              for (i = _i = 0, _len = decrypted_keys.length; _i < _len; i = ++_i) {
                decrypted_key = decrypted_keys[i];
                if (!decrypted_key) {
                  continue;
                }
                _this.my_aes_keys[rows[i].directory] = decrypted_key;
              }
              return cb(i);
            });
          };
        })(this));
      } else {
        return cb(false);
      }
    };

    MessageListInbox.prototype.decryptNewSecrets = function(parsed_db, cb) {
      var known_addresses, last_parsed, query, user_address, user_last_parsed, where, _ref;
      last_parsed = 0;
      known_addresses = [];
      _ref = parsed_db.last_secret;
      for (user_address in _ref) {
        user_last_parsed = _ref[user_address];
        last_parsed = Math.max(user_last_parsed, last_parsed);
        known_addresses.push("'" + user_address + "'");
      }
      this.log("Last parsed secret:", Date(last_parsed));
      if (known_addresses.length > 0) {
        where = "WHERE date_added > " + (last_parsed - 60 * 60 * 24 * 1000) + " OR directory NOT IN (" + (known_addresses.join(",")) + ")";
      } else {
        where = "";
      }
      query = "SELECT * FROM secret\nLEFT JOIN json USING (json_id)\n" + where + "\nORDER BY date_added ASC";
      return Page.cmd("dbQuery", [query], (function(_this) {
        return function(db_res) {
          var db_rows, row, secrets, _i, _len;
          if (!db_res.length) {
            cb(false);
            return false;
          }
          db_rows = [];
          for (_i = 0, _len = db_res.length; _i < _len; _i++) {
            row = db_res[_i];
            if ((parsed_db.last_secret[row.directory] == null) || parsed_db.last_secret[row.directory] < row.date_added) {
              db_rows.push(row);
            }
          }
          secrets = (function() {
            var _j, _len1, _results;
            _results = [];
            for (_j = 0, _len1 = db_rows.length; _j < _len1; _j++) {
              row = db_rows[_j];
              _results.push(row.encrypted);
            }
            return _results;
          })();
          return Page.cmd("eciesDecrypt", [secrets], function(aes_keys) {
            var aes_key, db_row, i, new_secrets, _j, _len1;
            new_secrets = {};
            for (i = _j = 0, _len1 = aes_keys.length; _j < _len1; i = ++_j) {
              aes_key = aes_keys[i];
              db_row = db_rows[i];
              if (aes_key) {
                new_secrets[db_row.directory] = db_row.date_added;
                parsed_db.my_secret[db_row.directory] = db_row.date_added;
                _this.my_aes_keys[db_row.directory] = aes_key;
              }
              parsed_db.last_secret[db_row.directory] = db_row.date_added;
            }
            return cb(new_secrets);
          });
        };
      })(this));
    };

    MessageListInbox.prototype.decryptNewMessages = function(parsed_db, new_secrets, cb) {
      var aes_key, found, group, last_parsed, new_addresses, parsed_sql, query, user_address, where, _ref, _ref1;
      parsed_sql = [];
      group = [];
      _ref = parsed_db.last_message;
      for (user_address in _ref) {
        last_parsed = _ref[user_address];
        group.push("(directory = '" + user_address + "' AND date_added > " + last_parsed + ")");
        if (group.length === 100) {
          parsed_sql.push("(" + group.join(" OR ") + ")");
          group = [];
        }
      }
      if (group.length > 0) {
        parsed_sql.push("(" + group.join(" OR ") + ")");
      }
      new_addresses = [];
      _ref1 = this.my_aes_keys;
      for (user_address in _ref1) {
        aes_key = _ref1[user_address];
        if (!parsed_db.last_message[user_address]) {
          new_addresses.push("'" + user_address + "'");
        }
      }
      if (parsed_sql.length > 0) {
        where = "WHERE " + (parsed_sql.join(' OR ')) + " OR directory IN (" + (new_addresses.join(",")) + ")";
      } else {
        where = "WHERE directory IN (" + (new_addresses.join(",")) + ")";
      }
      query = "SELECT * FROM message\nLEFT JOIN json USING (json_id)\n" + where + "\nORDER BY date_added ASC";
      found = 0;
      return Page.cmd("dbQuery", [query], (function(_this) {
        return function(db_res) {
          var address, aes_keys, encrypted_texts, row;
          if (db_res.length === 0) {
            cb(found);
            return;
          }
          aes_keys = (function() {
            var _ref2, _results;
            _ref2 = this.my_aes_keys;
            _results = [];
            for (address in _ref2) {
              aes_key = _ref2[address];
              _results.push(aes_key);
            }
            return _results;
          }).call(_this);
          encrypted_texts = (function() {
            var _i, _len, _results;
            _results = [];
            for (_i = 0, _len = db_res.length; _i < _len; _i++) {
              row = db_res[_i];
              _results.push(row.encrypted.split(","));
            }
            return _results;
          })();
          return Page.cmd("aesDecrypt", [encrypted_texts, aes_keys], function(decrypted_texts) {
            var db_row, decrypted_text, i, _i, _len, _ref2;
            for (i = _i = 0, _len = decrypted_texts.length; _i < _len; i = ++_i) {
              decrypted_text = decrypted_texts[i];
              db_row = db_res[i];
              if (!parsed_db.my_message[db_row.directory]) {
                parsed_db.my_message[db_row.directory] = [];
              }
              if (decrypted_text && (_ref2 = db_row.date_added, __indexOf.call(parsed_db.my_message[db_row.directory], _ref2) < 0)) {
                parsed_db.my_message[db_row.directory].push(db_row.date_added);
                found += 1;
              }
              parsed_db.last_message[db_row.directory] = db_row.date_added;
            }
            return cb(found);
          });
        };
      })(this));
    };

    MessageListInbox.prototype.loadMessages = function(parsed_db, limit, cb) {
      var address, ids, my_message_ids, query, _ref;
      my_message_ids = [];
      _ref = parsed_db.my_message;
      for (address in _ref) {
        ids = _ref[address];
        my_message_ids = my_message_ids.concat(ids);
      }
      query = "SELECT message.*, json.directory, keyvalue.value AS username FROM message\nLEFT JOIN json USING (json_id)\nLEFT JOIN json AS json_content ON json_content.directory = json.directory AND json_content.file_name = \"content.json\"\nLEFT JOIN keyvalue ON keyvalue.json_id = json_content.json_id AND keyvalue.key = \"cert_user_id\"\nWHERE date_added IN (" + (my_message_ids.join(",")) + ") AND date_added NOT IN (" + (Page.local_storage.deleted.join(",")) + ")\nORDER BY date_added DESC";
      if (limit) {
        query += " LIMIT " + (limit + 1);
      }
      return Page.cmd("dbQuery", [query], (function(_this) {
        return function(db_rows) {
          var aes_key, aes_keys, encrypted_messages, row;
          aes_keys = (function() {
            var _ref1, _results;
            _ref1 = this.my_aes_keys;
            _results = [];
            for (address in _ref1) {
              aes_key = _ref1[address];
              _results.push(aes_key);
            }
            return _results;
          }).call(_this);
          encrypted_messages = (function() {
            var _i, _len, _results;
            _results = [];
            for (_i = 0, _len = db_rows.length; _i < _len; _i++) {
              row = db_rows[_i];
              _results.push(row.encrypted.split(","));
            }
            return _results;
          })();
          return Page.cmd("aesDecrypt", [encrypted_messages, aes_keys], function(decrypted_messages) {
            var db_row, decrypted_message, i, message_row, message_rows, _i, _len;
            message_rows = [];
            for (i = _i = 0, _len = decrypted_messages.length; _i < _len; i = ++_i) {
              decrypted_message = decrypted_messages[i];
              if (!decrypted_message) {
                continue;
              }
              db_row = db_rows[i];
              message_row = Text.jsonDecode(decrypted_message);
              message_row.date_added = db_row.date_added;
              message_row.key = "inbox-" + db_row.directory + "-" + message_row.date_added;
              message_row.message_id = db_row.date_added;
              message_row.from = db_row.username;
              message_row.from_address = db_row.directory;
              message_row.folder = "inbox";
              if (!limit) {
                message_row.disable_animation = true;
              }
              if (i < limit || !limit) {
                message_rows.push(message_row);
              }
              message_rows.push(message_row);
            }
            _this.syncMessages(message_rows);
            _this.has_more = limit && decrypted_messages.length >= limit && !_this.nolimit_loaded;
            Page.projector.scheduleRender();
            return cb(message_rows);
          });
        };
      })(this));
    };

    MessageListInbox.prototype.getMessages = function(mode) {
      var limit;
      if (mode == null) {
        mode = "normal";
      }
      if (mode === "nolimit") {
        limit = null;
        this.nolimit_loaded = true;
      } else {
        limit = 15;
      }
      if (this.reload && Page.site_info) {
        this.loading = true;
        this.reload = false;
        this.logStart("getMessages");
        Page.on_local_storage.then((function(_this) {
          return function() {
            var parsed_db;
            parsed_db = Page.local_storage.parsed;
            _this.setLoadingMessage("Loading known AES keys...");
            return _this.decryptKnownAesKeys(parsed_db, function(loaded_keys) {
              _this.log("Loaded known AES keys");
              _this.setLoadingMessage("Decrypting new secrets...");
              return _this.decryptNewSecrets(parsed_db, function(new_secrets) {
                _this.log("New secrets found");
                if (!isEmpty(new_secrets)) {
                  Page.leftbar.reload_contacts = true;
                }
                _this.setLoadingMessage("Decrypting new messages...");
                return _this.decryptNewMessages(parsed_db, new_secrets, function(found) {
                  _this.log("New messages found", found);
                  _this.setLoadingMessage("Loading messages...");
                  if (!found && _this.messages.length > 0 && mode !== "nolimit") {
                    _this.logEnd("getMessages", "No new messages in mode " + mode);
                    Page.local_storage.parsed = parsed_db;
                    _this.loading = false;
                    _this.loaded = true;
                    return false;
                  }
                  return _this.loadMessages(parsed_db, limit, function(message_rows) {
                    _this.logEnd("getMessages", "Loaded messages in mode " + mode, message_rows.length);
                    Page.local_storage.parsed = parsed_db;
                    Page.saveLocalStorage();
                    _this.loading = false;
                    return _this.loaded = true;
                  });
                });
              });
            });
          };
        })(this));
      }
      return this.messages;
    };

    MessageListInbox.prototype.deleteMessage = function(message) {
      var _ref;
      MessageListInbox.__super__.deleteMessage.apply(this, arguments);
      if (_ref = message.row.message_id, __indexOf.call(Page.local_storage.deleted, _ref) < 0) {
        return Page.local_storage.deleted.push(message.row.message_id);
      }
    };

    MessageListInbox.prototype.save = function() {
      return Page.saveLocalStorage();
    };

    return MessageListInbox;

  })(MessageList);

  window.MessageListInbox = MessageListInbox;

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/MessageListSent.coffee ---- */


(function() {
  var MessageListSent,
    __extends = function(child, parent) { for (var key in parent) { if (__hasProp.call(parent, key)) child[key] = parent[key]; } function ctor() { this.constructor = child; } ctor.prototype = parent.prototype; child.prototype = new ctor(); child.__super__ = parent.prototype; return child; },
    __hasProp = {}.hasOwnProperty,
    __indexOf = [].indexOf || function(item) { for (var i = 0, l = this.length; i < l; i++) { if (i in this && this[i] === item) return i; } return -1; };

  MessageListSent = (function(_super) {
    __extends(MessageListSent, _super);

    function MessageListSent() {
      MessageListSent.__super__.constructor.apply(this, arguments);
      this.reload = true;
      this.loading = false;
      this.nolimit_loaded = false;
      this.cleanup = false;
      this.messages = [];
      this.title = "Sent";
    }

    MessageListSent.prototype.getMessages = function(mode, cb) {
      var limit, query;
      if (mode == null) {
        mode = "normal";
      }
      if (cb == null) {
        cb = null;
      }
      if (mode === "nolimit") {
        limit = null;
        this.nolimit_loaded = true;
      } else {
        limit = 15;
      }
      if (this.reload && Page.site_info && Page.site_info.cert_user_id && !this.loading) {
        this.reload = false;
        this.loading = true;
        query = "SELECT date_added, encrypted\nFROM message\nLEFT JOIN json USING (json_id)\nWHERE ?\nORDER BY date_added DESC";
        if (limit) {
          query += " LIMIT " + (limit + 1);
        }
        Page.cmd("dbQuery", [
          query, {
            "json.directory": Page.site_info.auth_address
          }
        ], (function(_this) {
          return function(db_rows) {
            var encrypted_messages, row;
            encrypted_messages = (function() {
              var _i, _len, _results;
              _results = [];
              for (_i = 0, _len = db_rows.length; _i < _len; _i++) {
                row = db_rows[_i];
                _results.push(row.encrypted.split(","));
              }
              return _results;
            })();
            _this.setLoadingMessage("Decrypting sent secrets...");
            return Page.user.getDecryptedSecretsSent(function(sent_secrets) {
              var address, aes_key, keys;
              keys = (function() {
                var _results;
                _results = [];
                for (address in sent_secrets) {
                  aes_key = sent_secrets[address];
                  _results.push(aes_key.replace(/.*:/, ""));
                }
                return _results;
              })();
              _this.setLoadingMessage("Decrypting sent messages...");
              return Page.cmd("aesDecrypt", [encrypted_messages, keys], function(decrypted_messages) {
                var decrypted_message, i, message_row, message_rows, usernames, _i, _len, _ref;
                message_rows = [];
                usernames = [];
                for (i = _i = 0, _len = decrypted_messages.length; _i < _len; i = ++_i) {
                  decrypted_message = decrypted_messages[i];
                  if (!decrypted_message) {
                    continue;
                  }
                  message_row = Text.jsonDecode(decrypted_message);
                  message_row.date_added = db_rows[i].date_added;
                  message_row.key = "sent-" + message_row.date_added;
                  message_row.message_id = db_rows[i].date_added;
                  message_row.sender = "Unknown";
                  message_row.folder = "sent";
                  if (!limit) {
                    message_row.disable_animation = true;
                  }
                  if (i < limit || !limit) {
                    message_rows.push(message_row);
                  }
                  if (_ref = message_row.to, __indexOf.call(usernames, _ref) < 0) {
                    usernames.push(message_row.to);
                  }
                }
                return Page.users.getAddress(usernames, function(addresses) {
                  var _j, _len1;
                  for (_j = 0, _len1 = message_rows.length; _j < _len1; _j++) {
                    message_row = message_rows[_j];
                    message_row.to_address = addresses[message_row.to];
                    if (message_row.to_address == null) {
                      message_row.to_address = "";
                    }
                  }
                  _this.syncMessages(message_rows);
                  _this.has_more = limit && decrypted_messages.length > limit && !_this.nolimit_loaded;
                  Page.projector.scheduleRender();
                  _this.loading = false;
                  _this.loaded = true;
                  if (cb) {
                    return cb(true);
                  }
                });
              });
            });
          };
        })(this));
      } else {
        if (cb) {
          cb(false);
        }
      }
      return this.messages;
    };

    MessageListSent.prototype.cleanupSecretsSent = function(cb) {
      if (this.has_more) {
        this.reload = true;
      }
      return this.getMessages("nolimit", (function(_this) {
        return function() {
          var message_nums;
          message_nums = _this.getMessagesBySender();
          return Page.user.getDecryptedSecretsSent(function(secrets_sent) {
            var address, secret, secret_id;
            for (address in secrets_sent) {
              secret = secrets_sent[address];
              if (message_nums[address]) {
                continue;
              }
              delete secrets_sent[address];
              _this.log("Cleanup sent secret sent", address);
              if (secret.indexOf(":") === -1) {
                continue;
              }
              secret_id = Base64Number.toNumber(secret.replace(/:.*/, ""));
              _this.log("Cleanup secret", address, secret_id);
              delete Page.user.data.secret[secret_id.toString()];
            }
            return Page.cmd("eciesEncrypt", [JSON.stringify(secrets_sent)], function(secrets_sent_encrypted) {
              if (!secrets_sent_encrypted) {
                if (cb) {
                  cb();
                }
                return false;
              }
              Page.user.data["secrets_sent"] = secrets_sent_encrypted;
              if (cb) {
                return cb();
              }
            });
          });
        };
      })(this));
    };

    MessageListSent.prototype.getMessagesBySender = function() {
      var message, messages, _i, _len, _name, _ref;
      messages = {};
      _ref = this.messages;
      for (_i = 0, _len = _ref.length; _i < _len; _i++) {
        message = _ref[_i];
        if (messages[_name = message.row.to_address] == null) {
          messages[_name] = [];
        }
        messages[message.row.to_address].push(message);
      }
      return messages;
    };

    MessageListSent.prototype.deleteMessage = function(message) {
      var senders;
      MessageListSent.__super__.deleteMessage.apply(this, arguments);
      delete Page.user.data.message[message.row.message_id];
      if (!this.has_more) {
        senders = this.getMessagesBySender();
        if (!senders[message.row.to_address]) {
          this.log("Removing sent secrets to user", message.row.to);
          return this.cleanup = true;
        }
      }
    };

    MessageListSent.prototype.save = function() {
      if (this.cleanup) {
        this.cleanupSecretsSent((function(_this) {
          return function() {
            return Page.user.saveData().then(function(res) {
              return _this.log("Delete result", res);
            });
          };
        })(this));
        return this.cleanup = false;
      } else {
        return Page.user.saveData().then((function(_this) {
          return function(res) {
            return _this.log("Delete result", res);
          };
        })(this));
      }
    };

    return MessageListSent;

  })(MessageList);

  window.MessageListSent = MessageListSent;

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/MessageLists.coffee ---- */


(function() {
  var MessageLists,
    __bind = function(fn, me){ return function(){ return fn.apply(me, arguments); }; },
    __extends = function(child, parent) { for (var key in parent) { if (__hasProp.call(parent, key)) child[key] = parent[key]; } function ctor() { this.constructor = child; } ctor.prototype = parent.prototype; child.prototype = new ctor(); child.__super__ = parent.prototype; return child; },
    __hasProp = {}.hasOwnProperty;

  MessageLists = (function(_super) {
    __extends(MessageLists, _super);

    function MessageLists() {
      this.render = __bind(this.render, this);
      this.inbox = new MessageListInbox(this);
      this.sent = new MessageListSent(this);
      this.active = this.inbox;
      this.message_active = null;
    }

    MessageLists.prototype.getActive = function() {
      return this.active;
    };

    MessageLists.prototype.setActive = function(name) {
      this.active.deselectMessages();
      return this.active = this[name];
    };

    MessageLists.prototype.getActiveMessage = function() {
      return this.getActive().message_active;
    };

    MessageLists.prototype.render = function() {
      return h("div.MessageLists", [this.active.render()]);
    };

    MessageLists.prototype.onSiteInfo = function(site_info) {
      this.sent.reload = true;
      return this.inbox.reload = true;
    };

    return MessageLists;

  })(Class);

  window.MessageLists = MessageLists;

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/MessageShow.coffee ---- */


(function() {
  var MessageShow,
    __bind = function(fn, me){ return function(){ return fn.apply(me, arguments); }; },
    __extends = function(child, parent) { for (var key in parent) { if (__hasProp.call(parent, key)) child[key] = parent[key]; } function ctor() { this.constructor = child; } ctor.prototype = parent.prototype; child.prototype = new ctor(); child.__super__ = parent.prototype; return child; },
    __hasProp = {}.hasOwnProperty;

  MessageShow = (function(_super) {
    __extends(MessageShow, _super);

    function MessageShow() {
      this.render = __bind(this.render, this);
      this.message = null;
    }

    MessageShow.prototype.setMessage = function(message) {
      this.message = message;
      return Page.projector.scheduleRender();
    };

    MessageShow.prototype.handleMultiDeleteClick = function() {
      var message, _i, _len, _ref;
      _ref = Page.message_lists.active.selected;
      for (_i = 0, _len = _ref.length; _i < _len; _i++) {
        message = _ref[_i];
        Page.message_lists.active.deleteMessage(message);
      }
      Page.message_lists.active.save();
      Page.message_lists.active.deselectMessages();
      return false;
    };

    MessageShow.prototype.render = function() {
      var _ref;
      console.log("MessageShow render");
      return h("div.MessageShow", [
        Page.site_info && (!Page.site_info.cert_user_id || (!Page.user.publickey && Page.user.inited)) ? start_screen.renderNocert() : Page.message_lists.getActive().selected.length > 0 ? h("div.selected", {
          "enterAnimation": Animation.show
        }, [
          h("a.icon.icon-trash.button-delete", {
            href: "#Delete",
            "title": "Delete messages",
            onclick: this.handleMultiDeleteClick
          }, ["Delete " + (Page.message_lists.getActive().selected.length) + " selected messages"])
        ]) : this.message ? this.message.renderShow() : Page.message_lists.getActive().messages.length > 0 || !Page.message_lists.getActive().loaded ? h("div.empty", {
          "enterAnimation": Animation.show
        }, ["No message selected"]) : ((_ref = Page.site_info) != null ? _ref.cert_user_id : void 0) && Page.user.loaded.result ? start_screen.renderNomessage() : h("div")
      ]);
    };

    return MessageShow;

  })(Class);

  window.MessageShow = MessageShow;

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/StartScreen.coffee ---- */


(function() {
  var StartScreen,
    bind = function(fn, me){ return function(){ return fn.apply(me, arguments); }; },
    extend = function(child, parent) { for (var key in parent) { if (hasProp.call(parent, key)) child[key] = parent[key]; } function ctor() { this.constructor = child; } ctor.prototype = parent.prototype; child.prototype = new ctor(); child.__super__ = parent.prototype; return child; },
    hasProp = {}.hasOwnProperty;

  StartScreen = (function(superClass) {
    extend(StartScreen, superClass);

    function StartScreen() {
      this.renderNomessage = bind(this.renderNomessage, this);
      this.renderNocert = bind(this.renderNocert, this);
      this.renderBody = bind(this.renderBody, this);
      this;
    }

    StartScreen.prototype.addDots = function(s) {
      return s = ".".repeat(18 - s.length) + s;
    };

    StartScreen.prototype.getTermLines = function() {
      var end_messages, end_publickeys, end_version, lines, percent, server_info, site_info;
      lines = [];
      server_info = Page.server_info;
      site_info = Page.site_info;
      end_version = server_info.version + " r" + server_info.rev;
      if (server_info.rev > 630) {
        end_version += " [OK]";
      } else {
        end_version += " [FAIL]";
      }
      if (site_info.bad_files === 0) {
        end_publickeys = "[DONE]";
      } else {
        if (site_info.workers > 0) {
          percent = Math.round(100 - (site_info.bad_files / site_info.started_task_num) * 100);
          end_publickeys = "[ " + percent + "%]";
        } else {
          end_publickeys = "[BAD:" + site_info.bad_files + "]";
        }
      }
      end_messages = "";
      if (site_info.bad_files === 0) {
        end_messages = "[DONE]";
      } else {
        if (site_info.workers > 0) {
          percent = Math.round(100 - (site_info.bad_files / site_info.started_task_num) * 100);
          end_messages += "[ " + percent + "%]";
        } else {
          end_messages += "[BAD:" + site_info.bad_files + "]";
        }
      }
      lines.push("Checking ZeroNet version......................." + (this.addDots(end_version)));
      lines.push("Checking public keys in database..............." + (this.addDots(end_publickeys)));
      lines.push("Checking messages in database.................." + (this.addDots(end_messages)));
      lines.push("Checking current user's public key in database........[NOT FOUND]");
      return lines.join("\n");
    };

    StartScreen.prototype.handleCertselect = function() {
      Page.cmd("certSelect", [[window.ZEROMAIL_LOCAL_DOMAIN || "local"]]);
      return false;
    };

    StartScreen.prototype.handleCreate = function() {
      Page.user.createData();
      return false;
    };

    StartScreen.prototype.renderBody = function(node) {
      return node.innerHTML = Text.renderMarked(node.textContent, {
        "sanitize": true
      });
    };

    StartScreen.prototype.renderNocert = function() {
      this.log("renderNocert");
      return h("div.StartScreen.nocert", {
        "key": "nocert",
        "afterCreate": Animation.addVisibleClass,
        "exitAnimation": Animation.slideUp
      }, [
        h("div.banner.term", {
          "afterCreate": Animation.termLines
        }, ["W E L C O M E   T O \n\n" + ($('#banner').textContent) + "\n\n\n"]), Page.server_info && Page.site_info ? h("div.term", {
          "afterCreate": Animation.termLines,
          "delay": 1,
          "delay_step": 0.2
        }, [this.getTermLines()]) : void 0, Page.server_info && Page.site_info ? Page.server_info.rev < 630 ? h("a.button.button-submit.button-certselect.disabled", {
          "href": "#Update",
          "afterCreate": Animation.show,
          "delay": 0,
          "style": "margin-left: -150px"
        }, ["Please update your ZeroNet client!"]) : !Page.site_info.cert_user_id ? h("a.button.button-submit.button-certselect", {
          "key": "certselect",
          "href": "#Select+username",
          "afterCreate": Animation.show,
          "delay": 1,
          onclick: this.handleCertselect
        }, ["Select username"]) : [
          h("div.term", {
            "key": "username-term",
            "afterCreate": Animation.termLines
          }, ["Selected username: " + Page.site_info.cert_user_id + ('.'.repeat(Math.max(22 - Page.site_info.cert_user_id.length, 0))) + "......[NO MAILBOX FOUND]"]), h("a.button.button-submit.button-certselect", {
            "key": "create",
            "href": "#Create+data",
            "afterCreate": Animation.show,
            "delay": 1,
            onclick: this.handleCreate
          }, ["Create my mailbox"])
        ] : void 0
      ]);
    };

    StartScreen.prototype.renderNomessage = function() {
      this.log("renderNomessage");
      return h("div.StartScreen.nomessage", {
        "key": "nomessage",
        "enterAnimation": Animation.slideDown
      }, [
        h("div.subject", ["Successful registration!"]), h("div.from", [
          "From: ", h("a.username", {
            "href": "#"
          }, "zeromail")
        ]), h("div.body", {
          afterCreate: this.renderBody
        }, ["Hello " + (Page.site_info.cert_user_id.replace(/@.*/, "")) + "!\n\nWelcome to the ZeroNet family. From now on anyone is able to message you in a simple and secure way.\n\n_Best regards: The users of ZeroNet_\n\n###### PS: To keep your identity safe don't forget to backup your **data/users.json** file!"])
      ]);
    };

    return StartScreen;

  })(Class);

  window.start_screen = new StartScreen();

}).call(this);



/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/User.coffee ---- */


(function() {
  var User,
    __extends = function(child, parent) { for (var key in parent) { if (__hasProp.call(parent, key)) child[key] = parent[key]; } function ctor() { this.constructor = child; } ctor.prototype = parent.prototype; child.prototype = new ctor(); child.__super__ = parent.prototype; return child; },
    __hasProp = {}.hasOwnProperty;

  User = (function(_super) {
    __extends(User, _super);

    function User() {
      this.data = null;
      this.publickey = null;
      this.data_size = null;
      this.file_rules = null;
      this.loading = false;
      this.inited = false;
      this.loaded = new Promise();
      this.loaded.then((function(_this) {
        return function(res) {
          _this.loading = false;
          _this.log("Loaded", res);
          return Page.projector.scheduleRender();
        };
      })(this));
    }

    User.prototype.getInnerPath = function(file_name) {
      if (file_name == null) {
        file_name = "data.json";
      }
      return "data/users/" + Page.site_info.auth_address + "/" + file_name;
    };

    User.prototype.getNewIndex = function(node) {
      var i, new_index, _i;
      new_index = Date.now();
      for (i = _i = 0; _i <= 100; i = ++_i) {
        if (!this.data[node][new_index + i]) {
          return new_index + i;
        }
      }
    };

    User.prototype.getDecryptedSecretsSent = function(cb) {
      var _ref;
      if (!((_ref = this.data) != null ? _ref.secrets_sent : void 0)) {
        cb(false);
        return false;
      }
      return Page.cmd("eciesDecrypt", [this.data.secrets_sent], (function(_this) {
        return function(decrypted) {
          if (decrypted) {
            return cb(JSON.parse(decrypted));
          } else {
            return cb(false);
          }
        };
      })(this));
    };

    User.prototype.getPublickey = function(user_address, cb) {
      return Page.cmd("fileGet", {
        "inner_path": "data/users/" + user_address + "/content.json",
        "required": false
      }, (function(_this) {
        return function(res) {
          var data;
          data = JSON.parse(res);
          if (data != null ? data.publickey : void 0) {
            return cb(data.publickey);
          } else {
            return Page.cmd("fileGet", {
              "inner_path": "data/users/" + user_address + "/data.json",
              "required": false
            }, function(res) {
              data = JSON.parse(res);
              if (data != null ? data.publickey : void 0) {
                return cb(data.publickey);
              } else {
                return Page.users.getArchived(function(archived) {
                  var _ref;
                  return cb((_ref = archived[user_address]) != null ? _ref["publickey"] : void 0);
                });
              }
            });
          }
        };
      })(this));
    };

    User.prototype.addSecret = function(secrets_sent, user_address, cb) {
      return this.getPublickey(user_address, (function(_this) {
        return function(publickey) {
          if (!publickey) {
            cb(false);
            return Page.cmd("wrapperNotification", ["error", "No publickey for user " + user_address]);
          }
          return Page.cmd("aesEncrypt", [""], function(res) {
            var encrypted, iv, key;
            key = res[0], iv = res[1], encrypted = res[2];
            return Page.cmd("eciesEncrypt", [key, publickey], function(secret) {
              var secret_index;
              secret_index = _this.getNewIndex("secret");
              _this.data.secret[secret_index] = secret;
              secrets_sent[user_address] = Base64Number.fromNumber(secret_index) + ":" + key;
              return Page.cmd("eciesEncrypt", [JSON.stringify(secrets_sent)], function(secrets_sent_encrypted) {
                if (!secrets_sent_encrypted) {
                  return cb(false);
                }
                _this.data["secrets_sent"] = secrets_sent_encrypted;
                return cb(key);
              });
            });
          });
        };
      })(this));
    };

    User.prototype.getSecret = function(user_address, cb) {
      return this.getDecryptedSecretsSent((function(_this) {
        return function(secrets_sent) {
          if (!secrets_sent) {
            secrets_sent = {};
          }
          if (secrets_sent[user_address]) {
            return cb(secrets_sent[user_address].replace(/.*:/, ""));
          } else {
            _this.log("Creating new secret for " + user_address);
            return _this.addSecret(secrets_sent, user_address, function(aes_key) {
              return cb(aes_key);
            });
          }
        };
      })(this));
    };

    User.prototype.loadData = function(cb) {
      var inner_path;
      inner_path = this.getInnerPath();
      this.log("Loading user file", inner_path);
      return Page.cmd("fileGet", {
        "inner_path": inner_path,
        "required": false
      }, (function(_this) {
        return function(get_res) {
          if (get_res) {
            _this.data_size = get_res.length;
            _this.data = JSON.parse(get_res);
            _this.publickey = _this.data.publickey;
            _this.loaded.resolve();
            if (cb) {
              cb(true);
            }
            _this.inited = true;
            return Page.projector.scheduleRender();
          } else {
            return _this.getPublickey(Page.site_info.auth_address, function(get_res) {
              if (get_res) {
                _this.publickey = get_res;
              }
              _this.data = {
                "secret": {},
                "secrets_sent": "",
                "publickey": _this.publickey,
                "message": {},
                "date_added": Date.now()
              };
              _this.loaded.resolve();
              _this.inited = true;
              if (cb) {
                cb(false);
              }
              return Page.projector.scheduleRender();
            });
          }
        };
      })(this));
    };

    User.prototype.createData = function() {
      var inner_path;
      inner_path = this.getInnerPath();
      this.log("Creating user file", inner_path);
      this.data = {
        "secret": {},
        "secrets_sent": "",
        "publickey": null,
        "message": {},
        "date_added": Date.now()
      };
      return Page.cmd("userPublickey", [], (function(_this) {
        return function(publickey_res) {
          if (publickey_res.error) {
            Page.cmd("wrapperNotification", ["error", "Publickey read error: " + publickey_res.error]);
            return _this.loaded.fail();
          } else {
            _this.data.publickey = publickey_res;
            // Real bug, found live: the render gate that decides whether to
            // show "Successful registration!" checks the top-level
            // `Page.user.publickey` (see loadData()'s own file-found branch,
            // which sets exactly that field) -- createData() here only ever
            // set `_this.data.publickey`, never `_this.publickey` itself, so
            // this stayed null forever after a fresh mailbox creation. Only
            // a full page reload fixed it, because THAT re-runs loadData()
            // from scratch, which finds the now-existing file and sets the
            // top-level field loadData()'s own way.
            _this.publickey = publickey_res;
            return _this.saveData().then(function(save_res) {
              // Real bug, found live: `loaded` already settled once during
              // the page's own initial load -- loadData() (below) resolves
              // it as soon as it discovers there's no mailbox yet, purely
              // to unblock the FIRST render (the "Create my mailbox"
              // screen itself). A Promise only ever fires its .then()
              // callback on its FIRST resolution (see the constructor,
              // just below, where that one-shot callback is registered);
              // resolving an already-settled `loaded` here is a silent
              // no-op, so the render that's supposed to show "Successful
              // registration!" never happened -- the page looked stuck on
              // "Create my mailbox" until something else (a full reload)
              // forced a fresh render. Scheduling one explicitly here,
              // rather than depending on `loaded`'s own one-shot .then(),
              // is what every other success handler in this file already
              // does after a real state change.
              _this.loaded.resolve(save_res);
              return Page.projector.scheduleRender();
            });
          }
        };
      })(this));
    };

    User.prototype.saveData = function(publish) {
      var inner_path, promise;
      if (publish == null) {
        publish = true;
      }
      promise = new Promise();
      inner_path = this.getInnerPath();
      this.data_size = Text.fileEncode(this.data).length;
      Page.cmd("fileWrite", [inner_path, Text.fileEncode(this.data)], (function(_this) {
        return function(write_res) {
          var content_inner_path;
          if (write_res !== "ok") {
            Page.cmd("wrapperNotification", ["error", "File write error: " + write_res]);
            promise.fail();
            return false;
          }
          // Local-identity fork: fileWrite only stages the raw bytes now
          // (this stack's non-root signing didn't exist at all until
          // contentSign landed) -- the covering data/users/<addr>/
          // content.json still needs its own cert-backed signature
          // before sitePublish has anything valid to push.
          content_inner_path = "data/users/" + Page.site_info.auth_address + "/content.json";
          return Page.cmd("contentSign", {"inner_path": content_inner_path}, function(sign_res) {
            if (sign_res && sign_res.error) {
              Page.cmd("wrapperNotification", ["error", "Content sign error: " + sign_res.error]);
              promise.fail();
              return false;
            }
            return Page.cmd("sitePublish", {
              "inner_path": inner_path
            }, function(publish_res) {
              if (publish_res === "ok") {
                Page.message_lists.sent.reload = true;
                Page.projector.scheduleRender();
                return promise.resolve();
              } else {
                return promise.resolve();
              }
            });
          });
        };
      })(this));
      return promise;
    };

    User.prototype.formatQuota = function() {
      if (!this.file_rules) {
        if (Page.site_info) {
          this.file_rules = {};
          Page.cmd("fileRules", this.getInnerPath(), (function(_this) {
            return function(res) {
              return _this.file_rules = res;
            };
          })(this));
        }
        return " ";
      } else {
        if (this.file_rules.max_size) {
          return (parseInt(this.data_size / 1024 + 1)) + "k/" + (parseInt(this.file_rules.max_size / 1024)) + "k";
        } else {
          return " ";
        }
      }
    };

    User.prototype.onSiteInfo = function(site_info) {
      var _ref;
      if (!this.loading && site_info.event && site_info.event[0] === "file_done" && site_info.event[1] === this.getInnerPath()) {
        this.loadData();
      }
      if (!this.data && !this.loading && site_info.cert_user_id && (!site_info.event || ((_ref = site_info.event) != null ? _ref[0] : void 0) === "cert_changed")) {
        this.loadData();
      }
      if (!site_info.cert_user_id) {
        return this.data = null;
      }
    };

    return User;

  })(Class);

  window.User = User;

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/Users.coffee ---- */


(function() {
  var Users,
    __bind = function(fn, me){ return function(){ return fn.apply(me, arguments); }; },
    __extends = function(child, parent) { for (var key in parent) { if (__hasProp.call(parent, key)) child[key] = parent[key]; } function ctor() { this.constructor = child; } ctor.prototype = parent.prototype; child.prototype = new ctor(); child.__super__ = parent.prototype; return child; },
    __hasProp = {}.hasOwnProperty,
    __indexOf = [].indexOf || function(item) { for (var i = 0, l = this.length; i < l; i++) { if (i in this && this[i] === item) return i; } return -1; };

  Users = (function(_super) {
    __extends(Users, _super);

    function Users() {
      this.getUsernames = __bind(this.getUsernames, this);
      this.getArchived = __bind(this.getArchived, this);
      this.user_address = {};
      this.archived = null;
    }

    Users.prototype.getArchived = function(cb) {
      if (this.archived) {
        return cb(this.archived);
      }
      return Page.cmd("fileGet", "data/archived.json", (function(_this) {
        return function(res) {
          _this.archived = JSON.parse(res);
          return cb(_this.archived);
        };
      })(this));
    };

    Users.prototype.applyLocalNames = function(usernames, cb) {
      return Page.cmd("localNameList", {}, function(local_names) {
        var addr;
        if (local_names && !local_names.error) {
          for (addr in local_names) {
            if (Object.prototype.hasOwnProperty.call(usernames, addr)) {
              usernames[addr] = local_names[addr];
            }
          }
        }
        return cb(usernames);
      });
    };

    Users.prototype.getUsernames = function(addresses, cb) {
      var query;
      query = "SELECT directory, value AS cert_user_id\nFROM json\nLEFT JOIN keyvalue USING (json_id)\nWHERE ? AND file_name = 'content.json' AND key = 'cert_user_id'";
      return Page.cmd("dbQuery", [
        query, {
          directory: addresses
        }
      ], (function(_this) {
        return function(rows) {
          var row, usernames, _i, _len;
          usernames = {};
          for (_i = 0, _len = rows.length; _i < _len; _i++) {
            row = rows[_i];
            usernames[row.directory] = row.cert_user_id;
            _this.user_address[row.cert_user_id] = row.directory;
          }
          if (rows.length === addresses.length) {
            _this.applyLocalNames(usernames, cb);
            return;
          }
          _this.log("Not found all username in sql, try to find in archived file");
          return _this.getArchived(function(archived) {
            var auth_address;
            for (auth_address in archived) {
              row = archived[auth_address];
              _this.user_address[row.cert_user_id] = auth_address;
              if (__indexOf.call(addresses, auth_address) >= 0) {
                if (usernames[auth_address] == null) {
                  usernames[auth_address] = row.cert_user_id;
                }
              }
            }
            return _this.applyLocalNames(usernames, cb);
          });
        };
      })(this));
    };

    Users.prototype.getAddress = function(usernames, cb) {
      var query, unknown_address, username;
      unknown_address = (function() {
        var _i, _len, _results;
        _results = [];
        for (_i = 0, _len = usernames.length; _i < _len; _i++) {
          username = usernames[_i];
          if (this.user_address[username] == null) {
            _results.push(username);
          }
        }
        return _results;
      }).call(this);
      if (unknown_address.length === 0) {
        cb(this.user_address);
        return;
      }
      query = "SELECT value, directory\nFROM keyvalue\nLEFT JOIN json USING (json_id)\nWHERE ?";
      return Page.cmd("dbQuery", [
        query, {
          "key": "cert_user_id",
          "value": unknown_address
        }
      ], (function(_this) {
        return function(rows) {
          var row, _i, _len;
          for (_i = 0, _len = rows.length; _i < _len; _i++) {
            row = rows[_i];
            _this.user_address[row.value] = row.directory;
          }
          return cb(_this.user_address);
        };
      })(this));
    };

    Users.prototype.getAll = function(cb) {
      return Page.cmd("dbQuery", ["SELECT value, directory FROM keyvalue LEFT JOIN json USING (json_id) WHERE key = 'cert_user_id'"], (function(_this) {
        return function(rows) {
          var row, _i, _len;
          if (rows.error) {
            return false;
          }
          _this.user_address = {};
          for (_i = 0, _len = rows.length; _i < _len; _i++) {
            row = rows[_i];
            _this.user_address[row.value] = row.directory;
          }
          return _this.getArchived(function(archived) {
            var auth_address;
            for (auth_address in archived) {
              row = archived[auth_address];
              _this.user_address[row.cert_user_id] = auth_address;
            }
            return cb(_this.user_address);
          });
        };
      })(this));
    };

    return Users;

  })(Class);

  window.Users = Users;

}).call(this);


/* ---- /1MaiL5gfBM1cyb4a8e3iiL8L5gXmoAJu27/js/ZeroMail.coffee ---- */


(function() {
  var ZeroMail,
    __bind = function(fn, me){ return function(){ return fn.apply(me, arguments); }; },
    __extends = function(child, parent) { for (var key in parent) { if (__hasProp.call(parent, key)) child[key] = parent[key]; } function ctor() { this.constructor = child; } ctor.prototype = parent.prototype; child.prototype = new ctor(); child.__super__ = parent.prototype; return child; },
    __hasProp = {}.hasOwnProperty;

  window.h = maquette.h;

  ZeroMail = (function(_super) {
    __extends(ZeroMail, _super);

    function ZeroMail() {
      this.onOpenWebsocket = __bind(this.onOpenWebsocket, this);
      return ZeroMail.__super__.constructor.apply(this, arguments);
    }

    ZeroMail.prototype.init = function() {
      this.params = {};
      this.site_info = null;
      this.on_site_info = new Promise();
      this.on_local_storage = new Promise();
      this.server_info = null;
      this.user = new User();
      this.users = new Users();
      return this.local_storage = null;
    };

    ZeroMail.prototype.createProjector = function() {
      this.leftbar = new Leftbar();
      this.message_lists = new MessageLists();
      this.message_show = new MessageShow();
      this.message_create = new MessageCreate();
      this.projector = maquette.createProjector();
      if (base.href.indexOf("?") === -1) {
        this.route("");
      } else {
        this.route(base.href.replace(/.*?\?/, ""));
      }
      this.projector.replace($("#MessageLists"), this.message_lists.render);
      this.projector.replace($("#MessageShow"), this.message_show.render);
      this.projector.replace($("#Leftbar"), this.leftbar.render);
      this.projector.merge($("#MessageCreate"), this.message_create.render);
      return setInterval((function() {
        return Page.projector.scheduleRender();
      }), 60 * 1000);
    };

    ZeroMail.prototype.route = function(query) {
      this.params = Text.parseQuery(query);
      this.log("Route", this.params);
      if (this.params.to) {
        this.on_site_info.then((function(_this) {
          return function() {
            return _this.message_create.show(_this.params.to);
          };
        })(this));
        this.cmd("wrapperReplaceState", [{}, "", this.createUrl("to", "")]);
      }
      if (this.params.url === "Sent") {
        return this.message_lists.setActive("sent");
      }
    };

    ZeroMail.prototype.createUrl = function(key, val) {
      var params, vals;
      params = JSON.parse(JSON.stringify(this.params));
      if (typeof key === "Object") {
        vals = key;
        for (key in keys) {
          val = keys[key];
          params[key] = val;
        }
      } else {
        params[key] = val;
      }
      return "?" + Text.encodeQuery(params);
    };

    ZeroMail.prototype.getLocalStorage = function() {
      return this.on_site_info.then((function(_this) {
        return function() {
          return _this.cmd("wrapperGetLocalStorage", [], function(_at_local_storage) {
            var _base, _base1, _base2, _base3, _base4, _base5, _base6;
            _this.local_storage = _at_local_storage;
            if (_this.local_storage == null) {
              _this.local_storage = {};
            }
            if ((_base = _this.local_storage).read == null) {
              _base.read = {};
            }
            if ((_base1 = _this.local_storage).deleted == null) {
              _base1.deleted = [];
            }
            if ((_base2 = _this.local_storage).parsed == null) {
              _base2.parsed = {};
            }
            if ((_this.local_storage.parsed.version != null) < 1) {
              _this.local_storage.parsed = {
                "version": 1
              };
              console.log("Reindexing...");
            }
            if ((_base3 = _this.local_storage.parsed).last_secret == null) {
              _base3.last_secret = {};
            }
            if ((_base4 = _this.local_storage.parsed).last_message == null) {
              _base4.last_message = {};
            }
            if ((_base5 = _this.local_storage.parsed).my_secret == null) {
              _base5.my_secret = {};
            }
            if ((_base6 = _this.local_storage.parsed).my_message == null) {
              _base6.my_message = {};
            }
            return _this.on_local_storage.resolve(_this.local_storage);
          });
        };
      })(this));
    };

    ZeroMail.prototype.saveLocalStorage = function(cb) {
      if (this.local_storage) {
        return this.cmd("wrapperSetLocalStorage", this.local_storage, (function(_this) {
          return function(res) {
            if (cb) {
              return cb(res);
            }
          };
        })(this));
      }
    };

    ZeroMail.prototype.onOpenWebsocket = function(e) {
      this.cmd("siteInfo", {}, (function(_this) {
        return function(site_info) {
          return _this.setSiteInfo(site_info);
        };
      })(this));
      return this.cmd("serverInfo", {}, (function(_this) {
        return function(server_info) {
          return _this.setServerInfo(server_info);
        };
      })(this));
    };

    ZeroMail.prototype.onRequest = function(cmd, params) {
      if (cmd === "setSiteInfo") {
        return this.setSiteInfo(params);
      } else {
        return this.log("Unknown command", params);
      }
    };

    ZeroMail.prototype.setSiteInfo = function(site_info) {
      var limit_interval, _ref;
      this.site_info = site_info;
      if (((_ref = site_info.event) != null ? _ref[0] : void 0) === "cert_changed") {
        this.getLocalStorage();
      }
      if (site_info.tasks > 20) {
        limit_interval = 60000;
      } else {
        limit_interval = 6000;
      }
      RateLimit(limit_interval, (function(_this) {
        return function() {
          _this.log("onSiteInfo RateLimit");
          _this.leftbar.onSiteInfo(site_info);
          _this.user.onSiteInfo(site_info);
          _this.message_create.onSiteInfo(site_info);
          return _this.message_lists.onSiteInfo(site_info);
        };
      })(this));
      this.projector.scheduleRender();
      this.getLocalStorage();
      return this.on_site_info.resolve();
    };

    ZeroMail.prototype.setServerInfo = function(server_info) {
      this.server_info = server_info;
      return this.projector.scheduleRender();
    };

    return ZeroMail;

  })(ZeroFrame);

  window.Page = new ZeroMail();

  window.Page.createProjector();

}).call(this);